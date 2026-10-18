/**
 * sqush-games-quota Cloudflare Worker
 *
 * Gatekeeper Worker for Cloudflare R2 bucket with quota enforcement.
 * Checks total bucket size before accepting PUT uploads, returning 507 Insufficient Storage
 * when the upload would exceed the configured MAX_BYTES.
 *
 * Supports both:
 * 1. Direct R2 list() scanning across all pages (zero setup, O(N)).
 * 2. Optional KV-based running total cache (O(1) fast path) when `QUOTA_KV` namespace is bound.
 */

// Default: 5 GiB (5 * 1024 * 1024 * 1024 bytes)
const DEFAULT_MAX_BYTES = 5 * 1024 * 1024 * 1024;
const KV_USAGE_KEY = "total_used_bytes";

/**
 * Scan all objects in R2 bucket and sum their size in bytes.
 */
async function scanBucketUsage(bucket) {
  let used = 0;
  let cursor = undefined;
  do {
    const listed = await bucket.list({ cursor });
    for (const obj of listed.objects) {
      used += obj.size;
    }
    cursor = listed.truncated ? listed.cursor : undefined;
  } while (cursor);
  return used;
}

/**
 * Get current bucket usage in bytes.
 * Uses KV if available, falling back to full R2 list() scan.
 */
async function getBucketUsage(env) {
  if (env.QUOTA_KV) {
    const cached = await env.QUOTA_KV.get(KV_USAGE_KEY);
    if (cached !== null) {
      const parsed = Number(cached);
      if (!Number.isNaN(parsed)) {
        return parsed;
      }
    }
    // KV miss or uninitialized: recalculate from R2 and populate KV cache
    const total = await scanBucketUsage(env.BUCKET);
    await env.QUOTA_KV.put(KV_USAGE_KEY, String(total));
    return total;
  }

  return await scanBucketUsage(env.BUCKET);
}

/**
 * Adjust the KV running total by a given delta (+/- bytes).
 */
async function updateKvUsage(env, deltaBytes) {
  if (!env.QUOTA_KV || deltaBytes === 0) return;
  const current = await getBucketUsage(env);
  const updated = Math.max(0, current + deltaBytes);
  await env.QUOTA_KV.put(KV_USAGE_KEY, String(updated));
  return updated;
}

/**
 * Check authorization token if authentication is enabled.
 */
function isAuthorized(request, env) {
  const requireAuth = env.REQUIRE_AUTH === "true" || !!env.AUTH_TOKEN;
  if (!requireAuth) return true;

  const authHeader = request.headers.get("authorization") || "";
  const tokenFromHeader = authHeader.startsWith("Bearer ")
    ? authHeader.slice(7).trim()
    : request.headers.get("x-auth-token") || "";

  return tokenFromHeader && tokenFromHeader === env.AUTH_TOKEN;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const pathname = url.pathname;
    const key = pathname.replace(/^\/+/, "");
    const maxBytes = Number(env.MAX_BYTES) || DEFAULT_MAX_BYTES;

    // ---- Admin / Info Endpoints ----
    if (pathname === "/" || pathname === "/_quota") {
      if (request.method !== "GET") {
        return new Response("Method not allowed", { status: 405 });
      }

      const used = await getBucketUsage(env);
      const remaining = Math.max(0, maxBytes - used);
      const percent = maxBytes > 0 ? ((used / maxBytes) * 100).toFixed(2) : "0.00";

      return Response.json({
        service: "sqush-games-quota",
        bucket: "sqush-games",
        used_bytes: used,
        max_bytes: maxBytes,
        remaining_bytes: remaining,
        used_mb: (used / (1024 * 1024)).toFixed(2),
        max_mb: (maxBytes / (1024 * 1024)).toFixed(2),
        percentage_used: `${percent}%`,
        quota_mode: env.QUOTA_KV ? "kv-cached (O(1))" : "direct-scan (O(N))",
      });
    }

    // Force recount & KV sync endpoint
    if (pathname === "/_sync") {
      if (!isAuthorized(request, env)) {
        return new Response("Unauthorized", { status: 401 });
      }
      if (request.method !== "POST") {
        return new Response("Method not allowed", { status: 405 });
      }

      const freshUsage = await scanBucketUsage(env.BUCKET);
      if (env.QUOTA_KV) {
        await env.QUOTA_KV.put(KV_USAGE_KEY, String(freshUsage));
      }
      return Response.json({
        status: "synced",
        used_bytes: freshUsage,
        used_mb: (freshUsage / (1024 * 1024)).toFixed(2),
        kv_updated: Boolean(env.QUOTA_KV),
      });
    }

    if (!key) {
      return new Response("Missing object key in path", { status: 400 });
    }

    // ---- Uploads: Enforce Quota ----
    if (request.method === "PUT") {
      if (!isAuthorized(request, env)) {
        return new Response("Unauthorized", { status: 401 });
      }

      const lengthHeader = request.headers.get("content-length");
      if (!lengthHeader) {
        return new Response(
          "Length Required: 'Content-Length' header must be present to verify bucket quota before storing.",
          { status: 411 }
        );
      }

      const incomingSize = Number(lengthHeader);
      if (Number.isNaN(incomingSize) || incomingSize < 0) {
        return new Response("Invalid Content-Length header.", { status: 400 });
      }

      // Check if this key already exists so we calculate net delta accurately
      const existing = await env.BUCKET.head(key);
      const existingSize = existing ? existing.size : 0;
      const netIncrease = incomingSize - existingSize;

      const currentUsed = await getBucketUsage(env);
      if (currentUsed + netIncrease > maxBytes) {
        return new Response(
          `Bucket quota exceeded. Used: ${currentUsed} bytes, Incoming: ${incomingSize} bytes, Limit: ${maxBytes} bytes.`,
          {
            status: 507, // 507 Insufficient Storage
            headers: {
              "X-Quota-Used": String(currentUsed),
              "X-Quota-Max": String(maxBytes),
            },
          }
        );
      }

      // Preserve metadata from client request
      const httpMetadata = {
        contentType: request.headers.get("content-type") || undefined,
        contentLanguage: request.headers.get("content-language") || undefined,
        contentDisposition: request.headers.get("content-disposition") || undefined,
        cacheControl: request.headers.get("cache-control") || undefined,
        contentEncoding: request.headers.get("content-encoding") || undefined,
      };

      await env.BUCKET.put(key, request.body, { httpMetadata });

      if (env.QUOTA_KV) {
        await updateKvUsage(env, netIncrease);
      }

      return new Response(`Stored ${key} (${incomingSize} bytes).`, {
        status: 201,
        headers: {
          "X-Quota-Remaining": String(Math.max(0, maxBytes - (currentUsed + netIncrease))),
        },
      });
    }

    // ---- Reads: Pass through ----
    if (request.method === "GET") {
      const object = await env.BUCKET.get(key);
      if (object === null) {
        return new Response("Not found", { status: 404 });
      }

      const headers = new Headers();
      object.writeHttpMetadata(headers);
      headers.set("etag", object.httpEtag);
      return new Response(object.body, { headers });
    }

    // ---- Metadata: Pass through ----
    if (request.method === "HEAD") {
      const object = await env.BUCKET.head(key);
      if (object === null) {
        return new Response("Not found", { status: 404 });
      }

      const headers = new Headers();
      object.writeHttpMetadata(headers);
      headers.set("etag", object.httpEtag);
      return new Response(null, { headers });
    }

    // ---- Deletes: Pass through & adjust KV ----
    if (request.method === "DELETE") {
      if (!isAuthorized(request, env)) {
        return new Response("Unauthorized", { status: 401 });
      }

      let deletedSize = 0;
      if (env.QUOTA_KV) {
        const existing = await env.BUCKET.head(key);
        if (existing) {
          deletedSize = existing.size;
        }
      }

      await env.BUCKET.delete(key);

      if (env.QUOTA_KV && deletedSize > 0) {
        await updateKvUsage(env, -deletedSize);
      }

      return new Response(`Deleted ${key}.`);
    }

    return new Response("Method not allowed", { status: 405 });
  },
};

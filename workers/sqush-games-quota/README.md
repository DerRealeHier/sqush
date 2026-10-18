# sqush-games-quota (Cloudflare R2 Gatekeeper Worker)

Gatekeeper Cloudflare Worker for the `sqush-games` R2 bucket. It inspects and enforces bucket storage quotas **before** accepting uploads (`PUT`), preventing the bucket from exceeding your configured limit (e.g. 5 GiB).

## Features

- **Pre-upload Quota Check**: Checks `Content-Length` and current bucket usage before accepting any upload. If the upload would exceed `MAX_BYTES`, it returns `507 Insufficient Storage` immediately without saving the file.
- **Dual-Mode Quota Tracking**:
  - **Direct Scan Mode (Default / Zero Setup)**: Iterates and sums R2 `list({ cursor })` across all pages.
  - **KV Cached Mode (High Performance)**: Maintains a running total in Cloudflare KV (`total_used_bytes`). Uploads check and increment the KV total in O(1) time without paginating R2.
- **Accurate Replacement Accounting**: If an existing file is replaced, the difference between the new size and the existing size (`netIncrease = incomingSize - existingSize`) is checked and tracked.
- **Pass-through Reads & Deletes**:
  - `GET /:key`: Streams object and propagates HTTP metadata and ETag.
  - `HEAD /:key`: Retrieves object metadata.
  - `DELETE /:key`: Deletes the object and decrements KV running total if enabled.
- **Status & Sync Endpoints**:
  - `GET /` or `GET /_quota`: Returns real-time JSON breakdown of used bytes, limit, percentage, and tracking mode.
  - `POST /_sync`: Forces a full bucket scan to re-synchronize the KV counter.
- **Optional Authentication**: Set `REQUIRE_AUTH = "true"` and `AUTH_TOKEN` to restrict write access to authorized services only.

---

## Quick Start & Deployment

### 1. Prerequisites
Ensure Node.js is installed. Move into this directory:
```bash
cd workers/sqush-games-quota
```

### 2. Configure `wrangler.jsonc`
The default `wrangler.jsonc` is configured for bucket `sqush-games` and a 5 GiB limit:
```jsonc
{
  "name": "sqush-games-quota",
  "main": "src/index.js",
  "compatibility_date": "2025-05-01",
  "r2_buckets": [
    {
      "binding": "BUCKET",
      "bucket_name": "sqush-games"
    }
  ],
  "vars": {
    "MAX_BYTES": "5368709120" // 5 GiB
  }
}
```

### 3. (Optional) Enable High-Performance KV Running Total
To avoid running a full `list()` scan on every upload as your bucket grows:
1. Create a KV namespace:
   ```bash
   npx wrangler kv namespace create QUOTA_KV
   ```
2. Copy the returned `id` and uncomment the `kv_namespaces` section in `wrangler.jsonc`:
   ```jsonc
   "kv_namespaces": [
     {
       "binding": "QUOTA_KV",
       "id": "your-kv-namespace-id"
     }
   ]
   ```

### 4. Deploy to Cloudflare
```bash
npx wrangler deploy
```

Once deployed, your Worker will be live at:
`https://sqush-games-quota.<your-subdomain>.workers.dev`

---

## sqush.io Integration

To route file uploads from `sqush.io` through this quota gatekeeper Worker instead of directly through S3 boto3:

In your root `.env` file:
```dotenv
R2_WORKER_URL=https://sqush-games-quota.<your-subdomain>.workers.dev
```

When `R2_WORKER_URL` is set, `services.file_service.upload_to_r2` will stream uploads to the Worker via HTTP `PUT`. If the bucket is full, the Worker responds with HTTP 507, stopping the upload and protecting your quota.

---

## API Reference

| Method | Path | Description | Response Status |
|--------|------|-------------|-----------------|
| `GET` | `/_quota` or `/` | Check storage usage & limits | `200 OK` (JSON) |
| `POST` | `/_sync` | Force full bucket scan & sync KV | `200 OK` |
| `PUT` | `/<key>` | Upload file with quota pre-check | `201 Created` / `507 Insufficient Storage` / `411 Length Required` |
| `GET` | `/<key>` | Download/read file | `200 OK` / `404 Not Found` |
| `HEAD` | `/<key>` | Read file headers | `200 OK` / `404 Not Found` |
| `DELETE` | `/<key>` | Delete file & update KV | `200 OK` |

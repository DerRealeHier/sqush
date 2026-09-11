import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone, timedelta
import requests

from extensions import db
import config
from models.ban import UserBan, ModerationScanState
from models.user import User, ProfileComment
from models.game import Review, UpdateComment
from models.roadmap import RoadmapItem, RoadmapComment
from models.message import DirectMessage

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """You are the official Sqush Gaming Platform Content Moderation AI.
Your job is to analyze user-generated gaming community content for critical safety and legal violations in German and English.

Evaluate each content item strictly into one of three verdict tiers:

1. "severe" (Extreme violations -> Permanent Ban):
   - Severe hate speech, dehumanizing racial slurs (e.g. the N-word in any variant/leetspeak, antisemitic, ethnic, or severe homophobic slurs).
   - Direct violent threats to kill, physically harm, or attack real persons.
   - Extreme illegal content or severe cyberbullying/hate raids.
   Verdict: "severe", ban_type: "permanent", offense_category: "hate_speech_slur"

2. "minor" (Privacy/Doxxing violations -> 30 Day Temporary Ban):
   - Malicious doxxing and leaking private personally identifiable information (PII) of real individuals without consent:
     Full real names (e.g. "Max Mustermann aus Hamburg"), private phone numbers, home addresses, private emails.
   Verdict: "minor", ban_type: "temporary", offense_category: "personal_info_leak"

3. "safe" (No violation -> No action):
   - Normal gaming discussions, harsh but legitimate criticism of games or mechanics, jokes, banter, normal usernames, bug reports, card trade offers, friendly insults without slurs.
   Verdict: "safe", ban_type: "none", offense_category: "none"

You MUST reply with valid, parseable JSON only:
{
  "results": [
    {
      "item_id": "<string or int matching item_id>",
      "verdict": "safe" | "minor" | "severe",
      "ban_type": "none" | "temporary" | "permanent",
      "offense_category": "none" | "personal_info_leak" | "hate_speech_slur",
      "public_reason": "<clean summary reason in English suitable for a public ban log, e.g. 'Leaking personal info / real full name (30 day timeout)' or 'Racial slur / Severe hate speech (Permanent ban)'>",
      "evidence_snippet": "<short censored snippet for admin eyes>",
      "explanation": "<short reasoning>"
    }
  ]
}
"""


def call_groq_moderation(items: list[dict]) -> list[dict]:
    """Sends a batch of content items to Groq API and returns the moderation results."""
    api_key = None
    try:
        from flask import current_app
        if current_app:
            api_key = current_app.config.get("GROQ_API_KEY")
    except Exception:
        pass

    if not api_key:
        api_key = config.GROQ_API_KEY or os.environ.get("GROQ_API_KEY")

    if not api_key:
        logger.warning("GROQ_API_KEY is not configured. Skipping Groq AI moderation call.")
        return []

    if not items:
        return []

    model_name = None
    try:
        from flask import current_app
        if current_app:
            model_name = current_app.config.get("GROQ_MODEL")
    except Exception:
        pass
    if not model_name:
        model_name = config.GROQ_MODEL or "llama-3.3-70b-versatile"

    prompt_user_content = json.dumps(items, ensure_ascii=False, indent=2)

    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Please evaluate the following {len(items)} items:\n\n{prompt_user_content}",
            },
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    try:
        response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=25)
        response.raise_for_status()
        raw_json = response.json()
        content = raw_json["choices"][0]["message"]["content"]
        data = json.loads(content)
        if isinstance(data, dict) and "results" in data:
            return data["results"]
        elif isinstance(data, list):
            return data
        return []
    except Exception as e:
        logger.error(f"Groq AI moderation error: {e}")
        return []


def is_email_banned(email: str) -> UserBan | None:
    """Checks if an email is currently actively banned."""
    if not email:
        return None
    email_clean = email.strip().lower()
    active_bans = UserBan.query.filter(
        UserBan.email == email_clean,
        UserBan.is_active == True,
    ).all()

    for ban in active_bans:
        if ban.is_currently_banned:
            return ban
        elif ban.is_expired:
            ban.is_active = False
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
    return None


def is_user_banned(user) -> UserBan | None:
    """Checks if a user account or user email is currently actively banned."""
    if not user:
        return None

    if isinstance(user, int):
        user_id = user
        email_clean = ""
    else:
        if hasattr(user, "is_authenticated") and not user.is_authenticated:
            return None
        user_id = getattr(user, "id", None)
        email_clean = (getattr(user, "email", "") or "").strip().lower()

    filters = [UserBan.is_active == True]
    if user_id and email_clean:
        filters.append((UserBan.user_id == user_id) | (UserBan.email == email_clean))
    elif user_id:
        filters.append(UserBan.user_id == user_id)
    elif email_clean:
        filters.append(UserBan.email == email_clean)
    else:
        return None

    query = UserBan.query.filter(*filters)
    active_bans = query.all()

    for ban in active_bans:
        if ban.is_currently_banned:
            return ban
        elif ban.is_expired:
            ban.is_active = False
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
    return None


def execute_ban(
    user_id: int | None = None,
    email: str | None = None,
    username: str | None = None,
    severity: str = "minor",
    offense_category: str = "personal_info_leak",
    reason: str | None = None,
    evidence_snippet: str | None = None,
    content_source: str | None = None,
    content_id: int | None = None,
    banned_by: str = "ai_automod",
    ai_model: str | None = None,
    user=None,
    evidence: str | None = None,
) -> UserBan:
    """Creates a UserBan and moderates offending content."""
    if evidence and not evidence_snippet:
        evidence_snippet = evidence

    if user is not None:
        user_id = user_id if user_id is not None else getattr(user, "id", None)
        email = email or getattr(user, "email", None)
        username = username or getattr(user, "username", None)

    now = datetime.now(timezone.utc)
    email_clean = (email or "").strip().lower()
    is_severe = (severity == "severe")

    # 30 days for doxxing/pii, permaban for slurs and hate speech xD
    ban_type = "permanent" if is_severe else "temporary"
    duration_days = None if is_severe else 30
    expires_at = None if is_severe else (now + timedelta(days=30))

    if not reason:
        if is_severe:
            reason = "Severe violation: Racial slur / Hate speech (Permanent ban)"
        else:
            reason = "Violation: Leaking personal info / real name (30 day timeout)"

    # check if they already have an active ban to upgrade or replace xD
    existing = UserBan.query.filter(
        ((UserBan.user_id == user_id) | (UserBan.email == email_clean)),
        UserBan.is_active == True,
    ).first()

    if existing:
        # upgrade temporary ban to permaban if they did something severe xD
        if is_severe and existing.ban_type == "temporary":
            existing.ban_type = "permanent"
            existing.duration_days = None
            existing.expires_at = None
            existing.severity = "severe"
            existing.offense_category = offense_category
            existing.reason = reason
            existing.evidence_snippet = evidence_snippet or existing.evidence_snippet
            existing.banned_at = now
            existing.banned_by = banned_by or existing.banned_by
            existing.ai_model = ai_model or existing.ai_model
            db.session.commit()
            _moderate_content(content_source, content_id)
            return existing

        # already permabanned, nothing more severe to do xD
        if existing.ban_type == "permanent":
            _moderate_content(content_source, content_id)
            return existing

        # existing temporary ban: update reason and extend if necessary (:
        existing.reason = reason
        existing.expires_at = expires_at
        existing.evidence_snippet = evidence_snippet or existing.evidence_snippet
        db.session.commit()
        _moderate_content(content_source, content_id)
        return existing

    ban = UserBan(
        user_id=user_id,
        email=email_clean,
        username=username or (email_clean.split("@")[0] if email_clean else "unknown"),
        ban_type=ban_type,
        duration_days=duration_days,
        severity=severity,
        offense_category=offense_category,
        reason=reason,
        evidence_snippet=evidence_snippet,
        content_source=content_source,
        content_id=content_id,
        banned_by=banned_by,
        ai_model=ai_model or config.GROQ_MODEL,
        banned_at=now,
        expires_at=expires_at,
        is_active=True,
    )
    db.session.add(ban)
    db.session.commit()

    # redact offending content immediately so nobody else sees the toxicity xD
    _moderate_content(content_source, content_id)
    return ban


# overwrite bad text so toxic stuff doesn't sit on the site (:
def _moderate_content(content_source: str | None, content_id: int | None):
    if not content_source or not content_id:
        return

    replacement_notice = "[This content was moderated for breaking community guidelines]"

    try:
        if content_source == "review":
            review = db.session.get(Review, content_id)
            if review:
                review.comment = replacement_notice
                db.session.commit()
        elif content_source == "profile_comment":
            comment = db.session.get(ProfileComment, content_id)
            if comment:
                comment.content = replacement_notice
                db.session.commit()
        elif content_source == "update_comment":
            comment = db.session.get(UpdateComment, content_id)
            if comment:
                comment.content = replacement_notice
                db.session.commit()
        elif content_source == "roadmap_comment":
            comment = db.session.get(RoadmapComment, content_id)
            if comment:
                comment.content = replacement_notice
                db.session.commit()
        elif content_source == "roadmap_item":
            item = db.session.get(RoadmapItem, content_id)
            if item:
                item.description = replacement_notice
                db.session.commit()
        elif content_source == "direct_message":
            dm = db.session.get(DirectMessage, content_id)
            if dm:
                dm.content = "[Message moderated]"
                db.session.commit()
    except Exception as e:
        logger.error(f"Error moderating content {content_source} #{content_id}: {e}")
        db.session.rollback()


def unban_user(ban_id: int) -> bool:
    """Revokes an active ban."""
    ban = db.session.get(UserBan, ban_id)
    if not ban:
        return False
    ban.is_active = False
    db.session.commit()
    return True


def run_moderation_scan(app=None) -> dict:
    """Runs a 10-minute scan of newly generated user content and bans violators."""
    state = ModerationScanState.query.first()
    if not state:
        state = ModerationScanState(
            last_scanned_at=datetime.now(timezone.utc),
            last_user_id=0,
            last_review_id=0,
            last_profile_comment_id=0,
            last_update_comment_id=0,
            last_roadmap_comment_id=0,
            last_roadmap_item_id=0,
            last_message_id=0,
            items_scanned=0,
            bans_issued=0,
        )
        db.session.add(state)
        db.session.commit()

    items_to_moderate = []

    # 1. New users (checking username)
    new_users = User.query.filter(User.id > state.last_user_id).order_by(User.id.asc()).limit(50).all()
    for u in new_users:
        items_to_moderate.append({
            "item_id": f"user_{u.id}",
            "type": "username",
            "db_id": u.id,
            "user_id": u.id,
            "username": u.username,
            "email": u.email,
            "text": f"Username: {u.username}",
        })
    if new_users:
        state.last_user_id = max(u.id for u in new_users)

    # 2. New reviews
    new_reviews = Review.query.filter(Review.id > state.last_review_id).order_by(Review.id.asc()).limit(50).all()
    for r in new_reviews:
        if r.comment:
            user = r.user or db.session.get(User, r.user_id)
            items_to_moderate.append({
                "item_id": f"review_{r.id}",
                "type": "review",
                "db_id": r.id,
                "user_id": r.user_id,
                "username": user.username if user else f"user_{r.user_id}",
                "email": user.email if user else "",
                "text": r.comment,
            })
    if new_reviews:
        state.last_review_id = max(r.id for r in new_reviews)

    # 3. New profile comments
    new_prof_comments = ProfileComment.query.filter(ProfileComment.id > state.last_profile_comment_id).order_by(ProfileComment.id.asc()).limit(50).all()
    for c in new_prof_comments:
        user = c.author or db.session.get(User, c.author_id)
        items_to_moderate.append({
            "item_id": f"profile_comment_{c.id}",
            "type": "profile_comment",
            "db_id": c.id,
            "user_id": c.author_id,
            "username": user.username if user else f"user_{c.author_id}",
            "email": user.email if user else "",
            "text": c.content,
        })
    if new_prof_comments:
        state.last_profile_comment_id = max(c.id for c in new_prof_comments)

    # 4. New game update comments
    new_update_comments = UpdateComment.query.filter(UpdateComment.id > state.last_update_comment_id).order_by(UpdateComment.id.asc()).limit(50).all()
    for c in new_update_comments:
        user = c.user or db.session.get(User, c.user_id)
        items_to_moderate.append({
            "item_id": f"update_comment_{c.id}",
            "type": "update_comment",
            "db_id": c.id,
            "user_id": c.user_id,
            "username": user.username if user else f"user_{c.user_id}",
            "email": user.email if user else "",
            "text": c.content,
        })
    if new_update_comments:
        state.last_update_comment_id = max(c.id for c in new_update_comments)

    # 5. New roadmap comments
    new_rdm_comments = RoadmapComment.query.filter(RoadmapComment.id > state.last_roadmap_comment_id).order_by(RoadmapComment.id.asc()).limit(50).all()
    for c in new_rdm_comments:
        user = c.user or db.session.get(User, c.user_id)
        items_to_moderate.append({
            "item_id": f"roadmap_comment_{c.id}",
            "type": "roadmap_comment",
            "db_id": c.id,
            "user_id": c.user_id,
            "username": user.username if user else f"user_{c.user_id}",
            "email": user.email if user else "",
            "text": c.content,
        })
    if new_rdm_comments:
        state.last_roadmap_comment_id = max(c.id for c in new_rdm_comments)

    # 6. New roadmap items
    new_rdm_items = RoadmapItem.query.filter(RoadmapItem.id > state.last_roadmap_item_id).order_by(RoadmapItem.id.asc()).limit(50).all()
    for i in new_rdm_items:
        user = i.author or db.session.get(User, i.author_id)
        items_to_moderate.append({
            "item_id": f"roadmap_item_{i.id}",
            "type": "roadmap_item",
            "db_id": i.id,
            "user_id": i.author_id,
            "username": user.username if user else f"user_{i.author_id}",
            "email": user.email if user else "",
            "text": f"Title: {i.title}\n{i.description or ''}",
        })
    if new_rdm_items:
        state.last_roadmap_item_id = max(i.id for i in new_rdm_items)

    # 7. New direct messages
    new_dms = DirectMessage.query.filter(DirectMessage.id > state.last_message_id).order_by(DirectMessage.id.asc()).limit(50).all()
    for m in new_dms:
        user = m.sender or db.session.get(User, m.sender_id)
        items_to_moderate.append({
            "item_id": f"dm_{m.id}",
            "type": "direct_message",
            "db_id": m.id,
            "user_id": m.sender_id,
            "username": user.username if user else f"user_{m.sender_id}",
            "email": user.email if user else "",
            "text": m.content,
        })
    if new_dms:
        state.last_message_id = max(m.id for m in new_dms)

    state.last_scanned_at = datetime.now(timezone.utc)

    if not items_to_moderate:
        state.status = "no_new_items"
        db.session.commit()
        return {"items_scanned": 0, "bans_issued": 0, "status": "no_new_items"}

    # Call Groq AI API
    results = call_groq_moderation(items_to_moderate)
    item_map = {str(item["item_id"]): item for item in items_to_moderate}

    bans_count = 0
    for res in results:
        item_id_str = str(res.get("item_id"))
        verdict = res.get("verdict", "safe").lower()
        if verdict in ("minor", "severe"):
            source_item = item_map.get(item_id_str)
            if not source_item:
                continue

            user_id = source_item.get("user_id")
            email = source_item.get("email")
            username = source_item.get("username")

            # fallback to query user if email is empty
            if user_id and not email:
                u = db.session.get(User, user_id)
                if u:
                    email = u.email
                    username = u.username

            if not email:
                continue

            severity = "severe" if verdict == "severe" else "minor"
            offense_category = res.get("offense_category") or ("hate_speech_slur" if severity == "severe" else "personal_info_leak")
            public_reason = res.get("public_reason")
            evidence = res.get("evidence_snippet") or source_item.get("text", "")[:200]

            execute_ban(
                user_id=user_id,
                email=email,
                username=username or "Unbekannter Nutzer",
                severity=severity,
                offense_category=offense_category,
                reason=public_reason,
                evidence_snippet=evidence,
                content_source=source_item.get("type"),
                content_id=source_item.get("db_id"),
                banned_by="ai_automod",
                ai_model=config.GROQ_MODEL,
            )
            bans_count += 1

    state.items_scanned += len(items_to_moderate)
    state.bans_issued += bans_count
    state.status = "success"
    db.session.commit()

    return {
        "items_scanned": len(items_to_moderate),
        "bans_issued": bans_count,
        "status": "success",
    }


def start_background_moderation(app, interval_seconds: int = 600):
    """Starts a background daemon thread that runs moderation scans every interval_seconds."""
    def worker():
        logger.info(f"Groq AI Moderation background worker started (interval: {interval_seconds}s).")
        while True:
            time.sleep(interval_seconds)
            try:
                with app.app_context():
                    res = run_moderation_scan(app)
                    if res.get("bans_issued", 0) > 0:
                        logger.warning(f"AI Moderation scan complete: {res['bans_issued']} ban(s) issued from {res['items_scanned']} items.")
            except Exception as e:
                logger.error(f"Error in moderation background worker: {e}")

    thread = threading.Thread(target=worker, daemon=True, name="GroqModerationWorker")
    thread.start()
    return thread

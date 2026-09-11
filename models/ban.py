from datetime import datetime, timezone
from extensions import db


class UserBan(db.Model):
    __tablename__ = "user_ban"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    username = db.Column(db.String(64), nullable=False, index=True)
    email = db.Column(db.String(128), nullable=False, index=True)
    ban_type = db.Column(db.String(20), nullable=False, default="temporary")  # "temporary" or "permanent"
    duration_days = db.Column(db.Integer, nullable=True)  # e.g. 30, or None for permanent
    severity = db.Column(db.String(20), nullable=False, default="minor")  # "minor" or "severe"
    offense_category = db.Column(db.String(50), nullable=False)  # "personal_info_leak", "hate_speech_slur", "custom"
    reason = db.Column(db.String(255), nullable=False)  # public clean explanation
    evidence_snippet = db.Column(db.Text, nullable=True)  # internal snippet for admin review
    content_source = db.Column(db.String(50), nullable=True)  # "review", "profile_comment", "username", etc.
    content_id = db.Column(db.Integer, nullable=True)
    banned_by = db.Column(db.String(50), default="ai_automod")  # "ai_automod" or "admin"
    ai_model = db.Column(db.String(50), nullable=True)  # "llama-3.3-70b-versatile"
    banned_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    expires_at = db.Column(db.DateTime, nullable=True, index=True)  # None if permanent
    is_active = db.Column(db.Boolean, default=True, index=True)

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return exp <= datetime.now(timezone.utc)

    @property
    def is_currently_banned(self) -> bool:
        return self.is_active and not self.is_expired

    @property
    def badge_label(self) -> str:
        if self.ban_type == "permanent":
            return "PERMANENT"
        return f"{self.duration_days or 30} TAGE"


class ModerationScanState(db.Model):
    __tablename__ = "moderation_scan_state"

    id = db.Column(db.Integer, primary_key=True)
    last_scanned_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_user_id = db.Column(db.Integer, default=0)
    last_review_id = db.Column(db.Integer, default=0)
    last_profile_comment_id = db.Column(db.Integer, default=0)
    last_update_comment_id = db.Column(db.Integer, default=0)
    last_roadmap_comment_id = db.Column(db.Integer, default=0)
    last_roadmap_item_id = db.Column(db.Integer, default=0)
    last_message_id = db.Column(db.Integer, default=0)
    items_scanned = db.Column(db.Integer, default=0)
    bans_issued = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default="success")  # "success", "failed", "no_new_items"
    error_message = db.Column(db.Text, nullable=True)

from datetime import datetime, timezone
from extensions import db


# keeping track of cards our users pulled (:
class UserCard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    card_key = db.Column(db.String(50), nullable=False, index=True)
    quantity = db.Column(db.Integer, default=1, nullable=False)
    obtained_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref=db.backref("cards", lazy="dynamic"))


# trading cards with homies over dms (:
class CardTrade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    offered_card_key = db.Column(db.String(50), nullable=False)
    requested_card_key = db.Column(db.String(50), nullable=True)  # can be null if it is a free homie gift (:
    status = db.Column(db.String(20), default="pending", index=True)  # pending, accepted, declined, cancelled
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = db.Column(db.DateTime, nullable=True)

    sender = db.relationship("User", foreign_keys=[sender_id], backref=db.backref("sent_trades", lazy="dynamic"))
    receiver = db.relationship("User", foreign_keys=[receiver_id], backref=db.backref("received_trades", lazy="dynamic"))

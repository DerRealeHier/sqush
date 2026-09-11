from datetime import datetime, timezone
from extensions import db


# who is talking to who? Database model for direct messages
class DirectMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    # in case they wanna talk about a specific game with the dev or friend
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=True)
    # or swapping cards with homies (:
    trade_id = db.Column(db.Integer, db.ForeignKey("card_trade.id"), nullable=True)
    is_read = db.Column(db.Boolean, default=False, index=True)  # gotta know if they left you on read xD
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # linking sender and receiver
    sender = db.relationship("User", foreign_keys=[sender_id], backref=db.backref("sent_messages", lazy="dynamic"))
    recipient = db.relationship("User", foreign_keys=[recipient_id], backref=db.backref("received_messages", lazy="dynamic"))
    game = db.relationship("Game")
    trade = db.relationship("CardTrade", foreign_keys=[trade_id])

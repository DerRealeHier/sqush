from datetime import datetime, timezone
from extensions import db


class Purchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False, index=True)
    price_paid = db.Column(db.Float, nullable=True)  # what it actually cost at purchase time
    purchased_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Stripe references. These are required.
    stripe_checkout_session_id = db.Column(db.String(255), nullable=True, unique=True)
    stripe_payment_intent_id = db.Column(db.String(255), nullable=True, unique=True)

    # Refund state. Keep the purchase row so payment history is not destroyed.
    refunded = db.Column(db.Boolean, default=False, nullable=False)
    refunded_at = db.Column(db.DateTime, nullable=True)
    # Stripe Connect payout tracking
    dev_payout_amount = db.Column(db.Float, nullable=True)     # e.g. 90% of price_paid
    platform_fee_amount = db.Column(db.Float, nullable=True)   # e.g. 10% of price_paid
    stripe_transfer_id = db.Column(db.String(255), nullable=True) # Stripe Transfer ID (tr_xxx)
    payout_status = db.Column(db.String(50), default="pending")   # 'direct', 'transferred', 'pending', 'unconnected'

    game = db.relationship("Game", backref="purchases")


class Wishlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False, index=True)
    added_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    game = db.relationship("Game", backref="wishlisted_by")
    user = db.relationship("User", backref="wishlist_entries")
    #one game per user on the wishlist
    __table_args__ = (db.UniqueConstraint('user_id', 'game_id', name='unique_wishlist'),)


class CartItem(db.Model):
    # Guest use the Flask session
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False, index=True)
    added_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    game = db.relationship("Game", backref="cart_entries")
    user = db.relationship("User", backref="cart_items")

    __table_args__ = (db.UniqueConstraint('user_id', 'game_id', name='unique_cart_item'),)


class Gift(db.Model):
    # tracks every game gift. form one to another. I need this juicy data.
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False, index=True)
    # links back to the Stripe session so we can tie refunds to the right sender. Yeah If I buy you a game and you refund it, you should not keep the money!
    stripe_checkout_session_id = db.Column(db.String(255), nullable=True, unique=True)
    stripe_payment_intent_id = db.Column(db.String(255), nullable=True)
    message = db.Column(db.String(500), nullable=True)  # optional greeting, OPTIONAL GUYS. ITS OPTIONAL
    sent_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    sender = db.relationship("User", foreign_keys=[sender_id], backref="gifts_sent")
    recipient = db.relationship("User", foreign_keys=[recipient_id], backref="gifts_received")
    game = db.relationship("Game", backref="gift_purchases")


class Tip(db.Model):
    # Tip Jar for devs. Give them your lunch money (: direct donations form players
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    developer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    message = db.Column(db.String(500), nullable=True)
    supporter_name = db.Column(db.String(64), nullable=True)
    stripe_checkout_session_id = db.Column(db.String(255), nullable=True, unique=True)
    stripe_payment_intent_id = db.Column(db.String(255), nullable=True)
    # Stripe Connect payout tracking for tips
    dev_payout_amount = db.Column(db.Float, nullable=True)
    platform_fee_amount = db.Column(db.Float, nullable=True)
    stripe_transfer_id = db.Column(db.String(255), nullable=True)
    payout_status = db.Column(db.String(50), default="pending")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    tipper = db.relationship("User", foreign_keys=[user_id], backref="tips_sent")
    developer = db.relationship("User", foreign_keys=[developer_id], backref="tips_received")
    game = db.relationship("Game", backref="tips")


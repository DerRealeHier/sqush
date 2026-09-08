from datetime import datetime, timezone
from extensions import db


# custom library folders so games stay organized (:
class Collection(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    description = db.Column(db.String(250), nullable=True)
    color = db.Column(db.String(7), default="#ffeb3b")  # hex accent color for that snazzy border xD
    is_hidden = db.Column(db.Boolean, default=False)    # hide collections you don't wanna see right now (:
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref="collections")
    __table_args__ = (
        db.UniqueConstraint("user_id", "name", name="unique_collection_per_user"),
    )


class CollectionGame(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    collection_id = db.Column(db.Integer, db.ForeignKey("collection.id"), nullable=False, index=True)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False, index=True)
    added_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    collection = db.relationship(
        "Collection",
        backref=db.backref("games", cascade="all, delete-orphan", lazy=True)
    )
    game = db.relationship("Game", backref="collection_entries")
    __table_args__ = (
        db.UniqueConstraint("collection_id", "game_id", name="unique_collection_game"),
    )

from datetime import datetime, timezone
from extensions import db


# bundles of joy and cheap games (:

class Bundle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    image_path = db.Column(db.String(250))
    discount_percent = db.Column(db.Integer, default=0, nullable=False)
    is_published = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)

    owner = db.relationship(
        "User",
        foreign_keys=[owner_id],
        backref="owned_bundles"
    )

    @property
    def original_price(self):
        return round(sum(x.game.price for x in self.games), 2)

    @property
    def display_price(self):
        return round(
            self.original_price * (1 - self.discount_percent / 100),
            2
        )


class BundleGame(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bundle_id = db.Column(
        db.Integer,
        db.ForeignKey("bundle.id"),
        nullable=False,
        index=True
    )
    game_id = db.Column(
        db.Integer,
        db.ForeignKey("game.id"),
        nullable=False,
        index=True
    )

    bundle = db.relationship(
        "Bundle",
        backref=db.backref(
            "games",
            cascade="all, delete-orphan",
            lazy=True
        )
    )
    game = db.relationship("Game", backref="bundle_entries")

    __table_args__ = (
        db.UniqueConstraint(
            "bundle_id",
            "game_id",
            name="unique_bundle_game"
        ),
    )


class BundleCollaborator(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bundle_id = db.Column(
        db.Integer,
        db.ForeignKey("bundle.id"),
        nullable=False,
        index=True
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True
    )
    invited_by_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True
    )
    role = db.Column(
        db.String(20),
        default="contributor",
        nullable=False
    )
    status = db.Column(
        db.String(20),
        default="pending",
        nullable=False,
        index=True
    )

    bundle = db.relationship(
        "Bundle",
        backref=db.backref(
            "collaborators",
            cascade="all, delete-orphan",
            lazy=True
        )
    )
    user = db.relationship("User", foreign_keys=[user_id])
    invited_by = db.relationship(
        "User",
        foreign_keys=[invited_by_id]
    )

    __table_args__ = (
        db.UniqueConstraint(
            "bundle_id",
            "user_id",
            name="unique_bundle_collaborator"
        ),
    )

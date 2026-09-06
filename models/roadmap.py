from datetime import datetime, timezone
from extensions import db


class RoadmapItem(db.Model):
    __tablename__ = "roadmap_item"

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)

    #  'planned', 'in_progress', 'done'
    status = db.Column(db.String(20), default="planned", nullable=False, index=True)

    # 'feature', 'bug', 'improvement'
    category = db.Column(db.String(20), default="feature", nullable=False, index=True)

    is_dev_post = db.Column(db.Boolean, default=False)
    upvotes_count = db.Column(db.Integer, default=0, nullable=False, index=True)
    sort_order = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    game = db.relationship(
        "Game",
        backref=db.backref("roadmap_items", lazy=True, cascade="all, delete-orphan", order_by="RoadmapItem.created_at.desc()")
    )
    author = db.relationship("User", backref="created_roadmap_items")
    votes = db.relationship("RoadmapVote", backref="item", lazy=True, cascade="all, delete-orphan")
    comments = db.relationship(
        "RoadmapComment",
        backref="item",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="RoadmapComment.created_at.asc()"
    )

    @property
    def status_label(self):
        labels = {
            "planned": "Planned",
            "in_progress": "In Progress",
            "done": "Done",
        }
        return labels.get(self.status, self.status.capitalize())

    @property
    def category_label(self):
        labels = {
            "feature": "Feature",
            "bug": "Bug Report",
            "improvement": "Improvement",
        }
        return labels.get(self.category, self.category.capitalize())


class RoadmapVote(db.Model):
    __tablename__ = "roadmap_vote"

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("roadmap_item.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref="roadmap_votes")

    __table_args__ = (
        db.UniqueConstraint("item_id", "user_id", name="unique_roadmap_vote"),
    )


class RoadmapComment(db.Model):
    __tablename__ = "roadmap_comment"

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("roadmap_item.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref="roadmap_comments")

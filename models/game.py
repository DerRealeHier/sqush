from datetime import datetime, timezone
from extensions import db


#Database Model for the games
class Game(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    genre = db.Column(db.String(50), nullable=False)
    priority = db.Column(db.String(20), default="normal")
    tags = db.Column(db.String(200))  # My lovely Tags. take them apart with: ,    BUT DON'T DO THIS THEY HAVE FAMILY
    price = db.Column(db.Float, nullable=False)
    view_count = db.Column(db.Integer, default=0)  #We need the DATA!
    image_path = db.Column(db.String(250))
    video_path = db.Column(db.String(250))  # The link couldn't be that long (:
    description = db.Column(db.Text, nullable=True)  #You could just have no description. Tell your Players nothing xD
    download_path = db.Column(db.String(250), nullable=False)  #Better be able to find it
    demo_path = db.Column(db.String(250), nullable=True)  #optional demo
    is_on_sale = db.Column(db.Boolean, default=False, index=True)
    discount_percent = db.Column(db.Integer, default=0)  #Give them those 2%
    sale_end_date = db.Column(db.DateTime, nullable=True)  #Can't keep on forever xD
    reviews = db.relationship("Review", backref="game", lazy=True)
    #My Foreign Key (:
    developer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)


class GameUpdate(db.Model):
    # yea we wanna see these old things too
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False, index=True)
    file_path = db.Column(db.String(250), nullable=False)
    version_label = db.Column(db.String(50), nullable=True)  # e.g. "v1.2", optional
    patch_notes = db.Column(db.Text, nullable=True)
    view_count = db.Column(db.Integer, default=0)
    upvotes = db.Column(db.Integer, default=0)
    downvotes = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    # newest update first, everywhere we touch game.updates
    game = db.relationship("Game", backref=db.backref("updates", order_by="GameUpdate.created_at.desc()"))


class UpdateComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    update_id = db.Column(db.Integer, db.ForeignKey("game_update.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    update = db.relationship("GameUpdate", backref=db.backref("comments", order_by="UpdateComment.created_at.desc()"))
    user = db.relationship("User")


class UpdateVote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    update_id = db.Column(db.Integer, db.ForeignKey("game_update.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    vote_type = db.Column(db.String(10), nullable=False)  # "up" or "down"

    update = db.relationship("GameUpdate", backref="votes")
    __table_args__ = (db.UniqueConstraint('update_id', 'user_id', name='unique_update_vote'),)


class GameFollow(db.Model):
    # lets a user get notified whenever the game they follow ships a new GameUpdate
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False, index=True)
    followed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref="followed_games")
    game = db.relationship("Game", backref="game_followers")
    __table_args__ = (db.UniqueConstraint('user_id', 'game_id', name='unique_game_follow'),)


class Screenshot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False, index=True)
    image_path = db.Column(db.String(250), nullable=False)


class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False, index=True)
    video_path = db.Column(db.String(250), nullable=False)


class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False, index=True)
    is_positive = db.Column(db.Boolean, nullable=False)
    comment = db.Column(db.Text, nullable=True)
    helpful_count = db.Column(db.Integer, default=0)
    funny_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    user = db.relationship("User", backref="reviews")
    votes = db.relationship("ReviewVote", backref="review", lazy=True)


class ReviewVote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey("review.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    vote_type = db.Column(db.String(10), nullable=False)  # "helpful" or "funny". SteamLike xD
    __table_args__ = (db.UniqueConstraint('review_id', 'user_id', 'vote_type', name='unique_vote'),)


class GameStats(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    views = db.Column(db.Integer, default=0)
    wishlist_count = db.Column(db.Integer, default=0)
    purchase_count = db.Column(db.Integer, default=0)
    revenue = db.Column(db.Float, default=0.0)  # snapshot of all the revenue for that day

    game = db.relationship("Game", backref="stats_history")
    # one snapshot per game per day(its getting updated not a new datapoint everys day)
    __table_args__ = (db.UniqueConstraint('game_id', 'date', name='unique_game_stat_day'),)

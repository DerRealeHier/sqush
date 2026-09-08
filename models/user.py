from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash
from extensions import db


class Friendship(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    status = db.Column(db.String(20), default='pending', index=True)

    sender = db.relationship("User", foreign_keys=[sender_id])
    receiver = db.relationship("User", foreign_keys=[receiver_id])


#Database model for my Users <)
class User(UserMixin, db.Model):
    profile_image = db.Column(db.String(250), default="avatars/default.png")
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), nullable=False, unique=True)
    email = db.Column(db.String(128), nullable=False, unique=True)  #trash-mails must be allowed
    password_hash = db.Column(db.String(250), nullable=False)  #Quantum Computers shall fall
    role = db.Column(db.String(20), default="user")  #you should be the dev
    comments_enabled = db.Column(db.Boolean, default=True)  # profile owner can turn comments off completely
    email_verified = db.Column(db.Boolean, default=False)  # has to click the link in the mail first
    firebase_uid = db.Column(db.String(128), nullable=True, unique=True)  # set once they log in with Google
    hackclub_id = db.Column(db.String(128), nullable=True, unique=True)  # set once they link/login with Hack Club
    has_password = db.Column(db.Boolean, default=True)  # False for accounts that only ever used Google/Hack Club (random placeholder password)
    two_fa_enabled = db.Column(db.Boolean, default=True)  # user can turn the login code mail off on the settings page
    needs_username_setup = db.Column(db.Boolean, default=False)  # True right after a fresh Google signup, until they pick their own name
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    featured_badge_key = db.Column(db.String(50), nullable=True)  # badge key user chooses to showcase

    # stripe connect stuff so devs get direct cash (:
    stripe_connect_id = db.Column(db.String(255), nullable=True, unique=True)
    stripe_connect_payouts_enabled = db.Column(db.Boolean, default=False)
    stripe_connect_details_submitted = db.Column(db.Boolean, default=False)
    stripe_connect_charges_enabled = db.Column(db.Boolean, default=False)
    followed = db.relationship("User", secondary=Friendship.__table__,
                               primaryjoin=(Friendship.sender_id == id),
                               secondaryjoin=(Friendship.receiver_id == id),
                               backref="followers",
                               viewonly=True,
                               lazy="dynamic")
    #linking more than just one game
    games = db.relationship("Game", backref="user", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def recent_notifications(self):
        return Notification.query.filter_by(user_id=self.id).order_by(Notification.created_at.desc()).limit(5).all()


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)  #Who needs Info?
    message = db.Column(db.String(250), nullable=False)
    type = db.Column(db.String(50))
    is_read = db.Column(db.Boolean, default=False, index=True)
    # yeah it wasnt aware of time-zones before. Happens xD
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user = db.relationship("User", backref="notifications")


class ProfileComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # whose profile the comment was posted on
    profile_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    # who wrote the comment? It's me xD
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    profile_user = db.relationship("User", foreign_keys=[profile_user_id], backref="profile_comments")
    author = db.relationship("User", foreign_keys=[author_id])


class LoginOTP(db.Model):
    #short lived 2FA code sent by mail on every login. This happens every login
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    code_hash = db.Column(db.String(250), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref="login_otps")


class UserBadge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    badge_key = db.Column(db.String(50), nullable=False, index=True)
    unlocked_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = db.relationship("User", backref=db.backref("user_badges", cascade="all, delete-orphan", lazy="dynamic"))

    __table_args__ = (
        db.UniqueConstraint("user_id", "badge_key", name="unique_user_badge"),
    )

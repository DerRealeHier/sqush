import os
from flask import Flask, redirect, url_for, flash, request, session
from flask_login import current_user
import config
from extensions import db, login_manager, mail, limiter, migrate, email_serializer
from models import (
    Friendship,
    User,
    Notification,
    Game,
    GameUpdate,
    UpdateComment,
    UpdateVote,
    GameFollow,
    Purchase,
    Wishlist,
    CartItem,
    GameStats,
    ProfileComment,
    LoginOTP,
    Screenshot,
    Video,
    Review,
    ReviewVote,
    Bundle,
    BundleGame,
    BundleCollaborator,
    Collection,
    CollectionGame,
    Gift,
    Tip,
    UserBadge,
    DirectMessage,
    RoadmapItem,
    RoadmapVote,
    RoadmapComment,
)
from services import (
    connected_login_methods_count,
    bundle_role,
    load_user,
    send_email,
    _comic_email_shell,
    send_verification_email,
    send_email_change_verification,
    send_login_otp,
    allowed_file,
    allowed_game_file,
    save_file,
    get_clamd_client,
    scan_filestorage_for_malware,
    save_game_file,
    calculate_game_revenue,
    calculate_display_price,
    calculate_review_score,
    _get_tag_set,
    get_popular_games,
    get_recommended_games,
    update_daily_stats,
    check_sales_expiry,
    _generate_cart_token,
    _valid_cart_token,
    _merge_guest_cart,
    _compute_bundle_alerts,
    fulfill_checkout,
    fulfill_gift,
    get_featured_badge,
    get_user_badges,
)
from routes import register_blueprints


def create_app(config_override=None):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["SQLALCHEMY_DATABASE_URI"] = config.SQLALCHEMY_DATABASE_URI
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = config.SQLALCHEMY_TRACK_MODIFICATIONS
    app.config["UPLOAD_FOLDER"] = config.UPLOAD_FOLDER
    app.config["AVATAR_FOLDER"] = config.AVATAR_FOLDER
    app.config["HACKCLUB_CLIENT_ID"] = config.HACKCLUB_CLIENT_ID
    app.config["HACKCLUB_CLIENT_SECRET"] = config.HACKCLUB_CLIENT_SECRET
    app.config["HACKCLUB_REDIRECT_URI"] = config.HACKCLUB_REDIRECT_URI
    app.config["MAIL_SERVER"] = config.MAIL_SERVER
    app.config["MAIL_PORT"] = config.MAIL_PORT
    app.config["MAIL_USE_TLS"] = config.MAIL_USE_TLS
    app.config["MAIL_USERNAME"] = config.MAIL_USERNAME
    app.config["MAIL_PASSWORD"] = config.MAIL_PASSWORD
    app.config["MAIL_DEFAULT_SENDER"] = config.MAIL_DEFAULT_SENDER
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 86400

    if config_override:
        app.config.update(config_override)

    # Initialize extensions
    db.init_app(app)
    #Initiliaze Login
    login_manager.init_app(app)
    login_manager.login_view = "login"  #YOU BETTER LOGIN
    mail.init_app(app)
    limiter.init_app(app)
    #Yea I need that
    migrate.init_app(app, db)

    # Static asset caching headers
    @app.after_request
    def add_caching_headers(response):
        if request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=86400"
        return response

    # Context processors
    @app.context_processor
    def inject_global_data():
        data = {
            "Screenshot": Screenshot,
            "Video": Video,
            "Friendship": Friendship,
            "cart_token": _generate_cart_token(),
            "get_featured_badge": get_featured_badge,
            "get_user_badges": get_user_badges,
        }
        if current_user.is_authenticated:
            try:
                unread_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
                data["unread_count"] = unread_count
            except Exception as e:
                print(f"DEBUG: Notification Fehler: {e}")
                data["unread_count"] = 0

            try:
                data["recent_notifications"] = Notification.query.filter_by(
                    user_id=current_user.id
                ).order_by(Notification.created_at.desc()).limit(5).all()
            except Exception as e:
                data["recent_notifications"] = []

            try:
                data["current_user_featured_badge"] = get_featured_badge(current_user)
            except Exception as e:
                print(f"DEBUG: Featured badge error: {e}")
                data["current_user_featured_badge"] = None

            try:
                wishlist_ids = {
                    row[0]
                    for row in db.session.query(Wishlist.game_id)
                    .filter_by(user_id=current_user.id)
                    .all()
                }
                data["wishlist_ids"] = wishlist_ids
            except Exception as e:
                print(f"DEBUG: Wishlist Fehler: {e}")
                data["wishlist_ids"] = set()

            try:
                following_game_ids = {
                    row[0]
                    for row in db.session.query(GameFollow.game_id)
                    .filter_by(user_id=current_user.id)
                    .all()
                }
                data["following_game_ids"] = following_game_ids
            except Exception as e:
                print(f"DEBUG: GameFollow Fehler: {e}")
                data["following_game_ids"] = set()

            try:
                cart_ids = {
                    row[0]
                    for row in db.session.query(CartItem.game_id)
                    .filter_by(user_id=current_user.id)
                    .all()
                }
                data["cart_ids"] = cart_ids
                data["cart_count"] = len(cart_ids)
            except Exception as e:
                print(f"DEBUG: Cart Fehler: {e}")
                data["cart_ids"] = set()
                data["cart_count"] = 0

            # how many unread dms we got (:
            try:
                data["unread_messages_count"] = DirectMessage.query.filter_by(
                    recipient_id=current_user.id, is_read=False
                ).count()
            except Exception as e:
                print(f"DEBUG: DirectMessage count error: {e}")
                data["unread_messages_count"] = 0
        else:
            data["unread_count"] = 0
            data["recent_notifications"] = []
            data["unread_messages_count"] = 0
            data["current_user_featured_badge"] = None
            data["wishlist_ids"] = set()
            data["following_game_ids"] = set()
            # Guest cart lives in the Flask session as a list of game IDs
            guest_cart = session.get("guest_cart", [])
            data["cart_ids"] = set(guest_cart)
            data["cart_count"] = len(guest_cart)

        return data

    @app.errorhandler(429)
    def ratelimit_handler(e):
        # e.description holds flask limiters "X per Y" text
        flash(f"Too many attempts, slow down (: Try again in a bit. ({e.description})", "error")
        return redirect(request.referrer or url_for("home")), 429

    #our lovely routes xD
    register_blueprints(app)

    return app


# Stripe API Keys.
#secruity first huh? and then the Database
#Directory for Videos , Pictures and REAL GAME FILES. I wouldn't wanna pay for the Server ):
app = create_app()

#initilaize the Database
with app.app_context():
    print("DEBUG: Prüfe Database Tables und Spalten")
    db.create_all()
    try:
        from sqlalchemy import text, inspect
        inspector = inspect(db.engine)
        if "user" in inspector.get_table_names():
            columns = [c["name"] for c in inspector.get_columns("user")]
            if "created_at" not in columns:
                db.session.execute(text("ALTER TABLE user ADD COLUMN created_at DATETIME"))
            if "featured_badge_key" not in columns:
                db.session.execute(text("ALTER TABLE user ADD COLUMN featured_badge_key VARCHAR(50)"))
            
            indexes = [
                ("idx_game_dev", "game", "developer_id"),
                ("idx_game_sale", "game", "is_on_sale"),
                ("idx_game_update_game", "game_update", "game_id"),
                ("idx_game_update_created", "game_update", "created_at"),
                ("idx_update_comment_update", "update_comment", "update_id"),
                ("idx_screenshot_game", "screenshot", "game_id"),
                ("idx_video_game", "video", "game_id"),
                ("idx_review_game", "review", "game_id"),
                ("idx_review_user", "review", "user_id"),
                ("idx_friendship_sender", "friendship", "sender_id"),
                ("idx_friendship_receiver", "friendship", "receiver_id"),
                ("idx_profile_comment_user", "profile_comment", "profile_user_id"),
                ("idx_bundle_owner", "bundle", "owner_id"),
                ("idx_bundle_published", "bundle", "is_published"),
                ("idx_bundle_game_b", "bundle_game", "bundle_id"),
                ("idx_bundle_game_g", "bundle_game", "game_id"),
                ("idx_bundle_collab_b", "bundle_collaborator", "bundle_id"),
                ("idx_bundle_collab_u", "bundle_collaborator", "user_id"),
                ("idx_collection_user", "collection", "user_id"),
                ("idx_collection_game_c", "collection_game", "collection_id"),
                ("idx_collection_game_g", "collection_game", "game_id"),
                ("idx_roadmap_game", "roadmap_item", "game_id"),
                ("idx_roadmap_status", "roadmap_item", "status"),
                ("idx_roadmap_votes", "roadmap_item", "upvotes_count"),
                ("idx_roadmap_author", "roadmap_item", "author_id"),
                ("idx_roadmap_vote_item", "roadmap_vote", "item_id"),
                ("idx_roadmap_vote_user", "roadmap_vote", "user_id"),
                ("idx_roadmap_comment_item", "roadmap_comment", "item_id"),
            ]
            for idx_name, tbl, col in indexes:
                try:
                    db.session.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {tbl} ({col})"))
                except Exception:
                    pass

            db.session.commit()
    except Exception as e:
        print(f"DEBUG: SQLite column check notice: {e}")


if __name__ == "__main__":
    app.run(debug=True)
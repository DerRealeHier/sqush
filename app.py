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
        if request.path.startswith("/static/uploads/"):
            # Never cache uploads aggressively so replaced covers/avatars update immediately
            response.headers["Cache-Control"] = "no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=3600"
        return response

    @app.template_filter("asset_v")
    def asset_version_filter(filename):
        if not filename:
            return ""
        rel_path = filename.lstrip("/\\")
        full_path = os.path.join(app.root_path, "static", rel_path)
        try:
            mtime = int(os.path.getmtime(full_path))
            return f"{url_for('static', filename=rel_path)}?v={mtime}"
        except Exception:
            return url_for("static", filename=rel_path)

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
            "asset_v": asset_version_filter,
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
    try:
        db.create_all()
    except Exception as e:
        print(f"DEBUG: db.create_all notice: {e}")
    try:
        from sqlalchemy import text, inspect
        inspector = inspect(db.engine)
        table_names = inspector.get_table_names()
        if "user" in table_names:
            columns = [c["name"] for c in inspector.get_columns("user")]
            if "created_at" not in columns:
                db.session.execute(text("ALTER TABLE user ADD COLUMN created_at DATETIME"))
            if "featured_badge_key" not in columns:
                db.session.execute(text("ALTER TABLE user ADD COLUMN featured_badge_key VARCHAR(50)"))
            if "stripe_connect_id" not in columns:
                db.session.execute(text("ALTER TABLE user ADD COLUMN stripe_connect_id VARCHAR(255)"))
            if "stripe_connect_payouts_enabled" not in columns:
                db.session.execute(text("ALTER TABLE user ADD COLUMN stripe_connect_payouts_enabled BOOLEAN DEFAULT 0"))
            if "stripe_connect_details_submitted" not in columns:
                db.session.execute(text("ALTER TABLE user ADD COLUMN stripe_connect_details_submitted BOOLEAN DEFAULT 0"))
            if "stripe_connect_charges_enabled" not in columns:
                db.session.execute(text("ALTER TABLE user ADD COLUMN stripe_connect_charges_enabled BOOLEAN DEFAULT 0"))

        if "purchase" in table_names:
            p_cols = [c["name"] for c in inspector.get_columns("purchase")]
            if "dev_payout_amount" not in p_cols:
                db.session.execute(text("ALTER TABLE purchase ADD COLUMN dev_payout_amount FLOAT"))
            if "platform_fee_amount" not in p_cols:
                db.session.execute(text("ALTER TABLE purchase ADD COLUMN platform_fee_amount FLOAT"))
            if "stripe_transfer_id" not in p_cols:
                db.session.execute(text("ALTER TABLE purchase ADD COLUMN stripe_transfer_id VARCHAR(255)"))
            if "payout_status" not in p_cols:
                db.session.execute(text("ALTER TABLE purchase ADD COLUMN payout_status VARCHAR(50) DEFAULT 'pending'"))

        if "tip" in table_names:
            t_cols = [c["name"] for c in inspector.get_columns("tip")]
            if "dev_payout_amount" not in t_cols:
                db.session.execute(text("ALTER TABLE tip ADD COLUMN dev_payout_amount FLOAT"))
            if "platform_fee_amount" not in t_cols:
                db.session.execute(text("ALTER TABLE tip ADD COLUMN platform_fee_amount FLOAT"))
            if "stripe_transfer_id" not in t_cols:
                db.session.execute(text("ALTER TABLE tip ADD COLUMN stripe_transfer_id VARCHAR(255)"))
            if "payout_status" not in t_cols:
                db.session.execute(text("ALTER TABLE tip ADD COLUMN payout_status VARCHAR(50) DEFAULT 'pending'"))
        db.session.commit()

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
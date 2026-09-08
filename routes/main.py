import json
from flask import Blueprint, render_template, jsonify, request
from flask_login import current_user, login_required
from extensions import db
from models.game import Game, Screenshot, Video, GameUpdate, UpdateVote, GameFollow
from models.bundle import Bundle, BundleGame
from models.commerce import Tip
from services.game_service import (
    calculate_display_price,
    calculate_game_tips,
    get_recommended_games,
    update_daily_stats,
    check_sales_expiry,
)
import config

main_bp = Blueprint("main", __name__)


@main_bp.route("/api/mail-health")
def mail_health():
    from flask import current_app
    import config

    mail_user = current_app.config.get("MAIL_USERNAME") or config.MAIL_USERNAME
    mail_pwd = current_app.config.get("MAIL_PASSWORD") or config.MAIL_PASSWORD
    mail_sender = current_app.config.get("MAIL_DEFAULT_SENDER") or config.MAIL_DEFAULT_SENDER
    mail_server = current_app.config.get("MAIL_SERVER") or config.MAIL_SERVER

    to_email = request.args.get("to")
    auth_token = request.args.get("token")
    send_result = None
    if to_email and (auth_token == config.SECRET_KEY or (current_user.is_authenticated and getattr(current_user, "is_admin", False))):
        from services.mail_service import send_email
        try:
            success = send_email(to_email, "Sqush Mail Test", "<h1>It works!</h1><p>Test from Sqush platform</p>")
            send_result = "SUCCESS" if success else "FAILED"
        except Exception as e:
            send_result = f"EXCEPTION: {e}"

    return jsonify({
        "server": mail_server,
        "has_username": bool(mail_user),
        "username": mail_user or "(not set)",
        "has_password": bool(mail_pwd),
        "password_starts_with_re": bool(mail_pwd and mail_pwd.strip().startswith("re_")),
        "password_length": len(mail_pwd) if mail_pwd else 0,
        "default_sender": mail_sender or "(not set)",
        "test_send_to": to_email,
        "test_result": send_result,
    })


#This is for the home Page.
@main_bp.route("/")
def home():
    check_sales_expiry()  #checking
    sale_games = Game.query.filter_by(is_on_sale=True).all()

    for game in sale_games:
        game.display_price = calculate_display_price(game)

    # personalized recommendations, only makes sense for logged in folks
    recommended_games = get_recommended_games(current_user, limit=6)
    for game in recommended_games:
        game.display_price = calculate_display_price(game)
        tags = [t.strip().lower() for t in game.tags.split(",")] if game.tags else []
        game.tags_json = json.dumps(tags)

    return render_template('home.html', sale_games=sale_games, recommended_games=recommended_games)


#Store Page
@main_bp.route("/store")
def store_front():
    all_games = Game.query.all()
    #Sorting them after their genre.
    games_by_genre = {}
    # collect every distinct tag across the whole catalog so the filter panel can render checkboxes for them
    all_tags = set()
    for game in all_games:  #while true loop would be great here (; The performance would go crazy
        tags = [t.strip().lower() for t in game.tags.split(",")] if game.tags else []
        game.tags_json = json.dumps(tags)
        game.display_price = calculate_display_price(game)
        all_tags.update(tags)

        if game.genre not in games_by_genre:
            games_by_genre[game.genre] = []

        games_by_genre[game.genre].append(game)

    # Load all bundles with their games eagerly loaded
    bundles = Bundle.query.options(db.joinedload(Bundle.games).joinedload(BundleGame.game)).filter_by(is_published=True).all()
    return render_template("store.html", genres=games_by_genre, all_tags=sorted(all_tags), bundles=bundles)


@main_bp.route("/buy/<int:game_id>", methods=["GET", "POST"])
def buy(game_id):
    game = Game.query.get_or_404(game_id)
    game.display_price = calculate_display_price(game)
    return render_template("buy.html", game=game)


@main_bp.route("/buy_bundle/<int:bundle_id>", methods=["GET", "POST"])
@login_required
def buy_bundle(bundle_id):
    bundle = Bundle.query.get_or_404(bundle_id)
    # Nur erlauben, falls veröffentlicht ODER falls es ein angemeldeter Developer (Besitzer) ist
    if not bundle.is_published and not (current_user.is_authenticated and current_user.role == "dev"):
        return "Bundle not available yet", 404
    return render_template("buy_bundle.html", bundle=bundle)


#This Server would cry
@main_bp.route("/game/<int:game_id>")
def game_detail(game_id):
    game = Game.query.get_or_404(game_id)
    screenshots = Screenshot.query.filter_by(game_id=game.id).all()
    videos = Video.query.filter_by(game_id=game.id).all()
    reviews = game.reviews
    total_ratings = len(reviews)

    if total_ratings > 0:
        positive_count = sum(1 for r in reviews if r.is_positive)
        average_score = (positive_count / total_ratings) * 100
    else:
        average_score = 0

    #Lets do Math (:
    game.display_price = calculate_display_price(game)

    # follow status and my own up/downvotes on this game's updates, only relevant when logged in
    is_following = False
    my_update_votes = {}
    if current_user.is_authenticated:
        is_following = GameFollow.query.filter_by(user_id=current_user.id, game_id=game.id).first() is not None
        my_update_votes = {
            v.update_id: v.vote_type for v in
            UpdateVote.query.join(GameUpdate, UpdateVote.update_id == GameUpdate.id)
            .filter(GameUpdate.game_id == game.id, UpdateVote.user_id == current_user.id).all()
        }

    # fetch tips for this game so we can show who has deep pockets (:
    tips = Tip.query.filter_by(game_id=game.id).order_by(Tip.created_at.desc()).all()
    total_tips = sum(t.amount for t in tips)
    tips_count = len(tips)
    recent_tips = tips[:6]

    return render_template("game_detail.html", game=game, screenshots=screenshots, videos=videos,
                           average_score=average_score, reviews=reviews,
                           is_following=is_following, my_update_votes=my_update_votes,
                           total_tips=total_tips, tips_count=tips_count, recent_tips=recent_tips)


@main_bp.route("/bundle/<int:bundle_id>")
def bundle_detail(bundle_id):
    bundle = Bundle.query.get_or_404(bundle_id)
    if not bundle.is_published and not (current_user.is_authenticated and current_user.role == "dev"):
        return "Bundle not available yet", 404
    return render_template("bundle_detail.html", bundle=bundle)


@main_bp.route("/config")
def get_publishable_key():
    stripe_config = {"publicKey": config.stripe_keys["publishable_key"]}
    return jsonify(stripe_config)


@main_bp.route("/increment_view/<int:game_id>", methods=["POST"])
def increment_view(game_id):
    game = Game.query.get_or_404(game_id)
    game.view_count += 1
    db.session.commit()
    update_daily_stats(game)
    return jsonify({"status": "success", "views": game.view_count})


@main_bp.route("/game/<int:game_id>/demo")
def download_demo(game_id):
    import os
    from flask import redirect, url_for, flash, current_app, send_from_directory
    from services.file_service import generate_presigned_download_url

    game = Game.query.get_or_404(game_id)
    if not game.demo_path:
        flash("No demo available for this game.", "error")
        return redirect(url_for("main.game_detail", game_id=game.id))

    if config.R2_ENABLED:
        r2_key = game.demo_path
        if config.R2_PUBLIC_URL and r2_key.startswith(config.R2_PUBLIC_URL):
            r2_key = r2_key[len(config.R2_PUBLIC_URL):].lstrip("/")
        filename = f"{game.title}_demo.zip"
        if "." in game.demo_path:
            ext = game.demo_path.rsplit(".", 1)[1]
            filename = f"{game.title}_demo.{ext}"
        presigned_url = generate_presigned_download_url(r2_key, filename=filename)
        if presigned_url:
            return redirect(presigned_url)

    rel_path = game.demo_path.lstrip("/\\")
    full_path = os.path.join(current_app.root_path, "static", rel_path)
    if os.path.exists(full_path):
        directory = os.path.dirname(full_path)
        fname = os.path.basename(full_path)
        return send_from_directory(directory, fname, as_attachment=True)

    flash("Demo file not found on server.", "error")
    return redirect(url_for("main.game_detail", game_id=game.id))

import json
from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, flash
from flask_login import current_user, login_required
from extensions import db
from models.game import Game
from models.commerce import Purchase, Wishlist
from models.collection import Collection, CollectionGame
from services.game_service import calculate_display_price, update_daily_stats

library_bp = Blueprint("library", __name__)


@library_bp.route("/library")
@login_required
def library():
    purchases = Purchase.query.options(db.joinedload(Purchase.game)).filter_by(
        user_id=current_user.id,
        refunded=False
    ).order_by(Purchase.purchased_at.desc()).all()

    now = datetime.now(timezone.utc)

    library_games = []

    for purchase in purchases:
        purchased_at = purchase.purchased_at

        # SQLite may return naive datetimes. Like get better manners.
        if purchased_at.tzinfo is None:
            purchased_at = purchased_at.replace(tzinfo=timezone.utc)

        age = now - purchased_at

        # Refund is available for less than 14 days. You aint gonna get more time than that.
        refund_available = age < timedelta(days=14)

        days_remaining = max(0, 14 - age.days)

        library_games.append({
            "game": purchase.game,
            "purchase": purchase,
            "refund_available": refund_available,
            "days_remaining": days_remaining
        })

    # prepare custom folders for the library (:
    collections = Collection.query.options(db.joinedload(Collection.games)).filter_by(user_id=current_user.id).order_by(Collection.created_at).all()

    # games that already have a home
    assigned_game_ids = {
        cg.game_id
        for col in collections
        for cg in col.games
    }

    # checkmarks for each dropdown (:
    col_game_ids_map = {
        col.id: {cg.game_id for cg in col.games}
        for col in collections
    }

    return render_template(
        "library.html",
        library_games=library_games,
        collections=collections,
        assigned_game_ids=assigned_game_ids,
        col_game_ids_map=col_game_ids_map,
    )


# custom collection folders (:
@library_bp.route("/collections/create", methods=["POST"])
@login_required
def create_collection():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    color = request.form.get("color", "#ffeb3b")
    if not name:
        flash("Collection name cannot be empty.", "error")
        return redirect(url_for("library"))
    # make sure it's a real hex color (:
    if not (len(color) == 7 and color.startswith("#")):
        color = "#ffeb3b"
    existing = Collection.query.filter_by(user_id=current_user.id, name=name).first()
    if existing:
        flash(f'You already have a collection named "{name}".', "error")
        return redirect(url_for("library"))
    col = Collection(
        user_id=current_user.id,
        name=name,
        description=description or None,
        color=color,
    )
    db.session.add(col)
    db.session.commit()
    flash(f'Collection "{name}" created!', "success")
    return redirect(url_for("library"))


@library_bp.route("/collections/<int:collection_id>/delete", methods=["POST"])
@login_required
def delete_collection(collection_id):
    col = Collection.query.filter_by(id=collection_id, user_id=current_user.id).first_or_404()
    name = col.name
    db.session.delete(col)
    db.session.commit()
    flash(f'Collection "{name}" deleted.', "success")
    return redirect(url_for("library"))


@library_bp.route("/collections/<int:collection_id>/rename", methods=["POST"])
@login_required
def rename_collection(collection_id):
    col = Collection.query.filter_by(id=collection_id, user_id=current_user.id).first_or_404()
    new_name = request.form.get("name", "").strip()
    if not new_name:
        flash("Name cannot be empty.", "error")
        return redirect(url_for("library"))
    existing = Collection.query.filter_by(user_id=current_user.id, name=new_name).first()
    if existing and existing.id != col.id:
        flash(f'You already have a collection named "{new_name}".', "error")
        return redirect(url_for("library"))
    col.name = new_name
    db.session.commit()
    return redirect(url_for("library"))


@library_bp.route("/collections/<int:collection_id>/toggle/<int:game_id>", methods=["POST"])
@login_required
def toggle_game_collection(collection_id, game_id):

    col = Collection.query.filter_by(id=collection_id, user_id=current_user.id).first_or_404()
    entry = CollectionGame.query.filter_by(collection_id=collection_id, game_id=game_id).first()
    if entry:
        db.session.delete(entry)
        db.session.commit()
        return jsonify(success=True, action="removed", collection_id=collection_id, game_id=game_id)
    else:
        # Verify the game is actually in the user's library. Hope so
        owns = Purchase.query.filter_by(user_id=current_user.id, game_id=game_id, refunded=False).first()
        if not owns:
            return jsonify(error="Game not in library"), 403
        db.session.add(CollectionGame(collection_id=collection_id, game_id=game_id))
        db.session.commit()
        return jsonify(success=True, action="added", collection_id=collection_id, game_id=game_id)


@library_bp.route("/purchase/<int:game_id>", methods=["POST"])
@login_required
def purchase(game_id):
    # cheat button for local dev testing without real money lol
    existing_purchase = Purchase.query.filter_by(
        user_id=current_user.id,
        game_id=game_id
    ).first()

    if existing_purchase and not existing_purchase.refunded:
        return "Brochacho, you already own that", 400

    game = Game.query.get_or_404(game_id)

    # fresh purchase row so we don't mess up refund history if they buy it again xD
    new_purchase = Purchase(
        user_id=current_user.id,
        game_id=game_id,
        price_paid=calculate_display_price(game)
    )

    db.session.add(new_purchase)
    db.session.commit()
    update_daily_stats(game)
    return redirect(url_for("library"))


@library_bp.route("/toggle_wishlist/<int:game_id>", methods=["POST"])
@login_required
def toggle_wishlist(game_id):
    game = Game.query.get_or_404(game_id)

    existing = Wishlist.query.filter_by(user_id=current_user.id, game_id=game.id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        update_daily_stats(game)
        return jsonify({"status": "removed", "on_wishlist": False, "count": len(game.wishlisted_by)})
    else:
        entry = Wishlist(user_id=current_user.id, game_id=game.id)
        db.session.add(entry)
        db.session.commit()
        update_daily_stats(game)
        return jsonify({"status": "added", "on_wishlist": True, "count": len(game.wishlisted_by)})


@library_bp.route("/wishlist")
@login_required
def wishlist():
    entries = Wishlist.query.filter_by(user_id=current_user.id).order_by(Wishlist.added_at.desc()).all()
    games = []
    for entry in entries:
        game = entry.game
        game.display_price = calculate_display_price(game)
        # same tags logic like in store front youm know
        tags = [t.strip().lower() for t in game.tags.split(",")] if game.tags else []
        game.tags_json = json.dumps(tags)
        games.append(game)
    return render_template("wishlist.html", games=games)


@library_bp.route("/library/download/<int:game_id>")
@login_required
def download_game(game_id):
    import os
    from flask import current_app, send_from_directory
    from services.file_service import generate_presigned_download_url
    import config

    game = Game.query.get_or_404(game_id)
    has_purchased = Purchase.query.filter_by(
        user_id=current_user.id,
        game_id=game.id,
        refunded=False
    ).first() is not None

    is_author = (game.developer_id == current_user.id)
    is_admin = getattr(current_user, "is_admin", False)

    if not (has_purchased or is_author or is_admin):
        flash("You need to own this game before downloading it.", "error")
        return redirect(url_for("main.game_detail", game_id=game.id))

    if not game.download_path:
        flash("No download file available for this game.", "error")
        return redirect(url_for("library.library"))

    # grab from r2 storage if enabled
    if config.R2_ENABLED:
        r2_key = game.download_path
        if config.R2_PUBLIC_URL and r2_key.startswith(config.R2_PUBLIC_URL):
            r2_key = r2_key[len(config.R2_PUBLIC_URL):].lstrip("/")
        filename = f"{game.title}.zip"
        if "." in game.download_path:
            ext = game.download_path.rsplit(".", 1)[1]
            filename = f"{game.title}.{ext}"
        presigned_url = generate_presigned_download_url(r2_key, filename=filename)
        if presigned_url:
            return redirect(presigned_url)

    # fallback to local files
    rel_path = game.download_path.lstrip("/\\")
    full_path = os.path.join(current_app.root_path, "static", rel_path)
    if os.path.exists(full_path):
        directory = os.path.dirname(full_path)
        fname = os.path.basename(full_path)
        return send_from_directory(directory, fname, as_attachment=True)

    flash("File not found on server.", "error")
    return redirect(url_for("library.library"))

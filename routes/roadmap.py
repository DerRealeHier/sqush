from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, flash, abort
from flask_login import current_user, login_required
from extensions import db
from models.game import Game
from models.user import Notification
from models.roadmap import RoadmapItem, RoadmapVote, RoadmapComment

roadmap_bp = Blueprint("roadmap", __name__)


@roadmap_bp.route("/game/<int:game_id>/roadmap")
def game_roadmap(game_id):
    game = Game.query.get_or_404(game_id)

    category_filter = request.args.get("category", "all").strip().lower()
    sort_by = request.args.get("sort", "votes").strip().lower()

    query = RoadmapItem.query.filter_by(game_id=game.id)

    if category_filter in ("feature", "bug", "improvement"):
        query = query.filter_by(category=category_filter)

    if sort_by == "newest":
        query = query.order_by(RoadmapItem.created_at.desc())
    else:  # default 'votes'
        query = query.order_by(RoadmapItem.upvotes_count.desc(), RoadmapItem.created_at.desc())

    all_items = query.all()

    # split into 3 nice columns like trello (:
    planned_items = [item for item in all_items if item.status == "planned"]
    in_progress_items = [item for item in all_items if item.status == "in_progress"]
    done_items = [item for item in all_items if item.status == "done"]

    # quick card counting
    total_items = RoadmapItem.query.filter_by(game_id=game.id).count()
    feature_count = RoadmapItem.query.filter_by(game_id=game.id, category="feature").count()
    bug_count = RoadmapItem.query.filter_by(game_id=game.id, category="bug").count()
    done_count = RoadmapItem.query.filter_by(game_id=game.id, status="done").count()

    is_dev = False
    user_voted_ids = set()

    if current_user.is_authenticated:
        is_dev = (current_user.id == game.developer_id) or (getattr(current_user, "role", "") == "admin")
        voted_records = RoadmapVote.query.filter_by(user_id=current_user.id).all()
        user_voted_ids = {v.item_id for v in voted_records}

    return render_template(
        "game_roadmap.html",
        game=game,
        planned_items=planned_items,
        in_progress_items=in_progress_items,
        done_items=done_items,
        total_items=total_items,
        feature_count=feature_count,
        bug_count=bug_count,
        done_count=done_count,
        category_filter=category_filter,
        sort_by=sort_by,
        is_dev=is_dev,
        user_voted_ids=user_voted_ids,
    )


@roadmap_bp.route("/game/<int:game_id>/roadmap/item", methods=["POST"])
@login_required
def create_roadmap_item(game_id):
    game = Game.query.get_or_404(game_id)

    is_dev = (current_user.id == game.developer_id) or (getattr(current_user, "role", "") == "admin")

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    category = request.form.get("category", "feature").strip().lower()

    if not title:
        flash("Title is required for roadmap items.", "error")
        return redirect(url_for("roadmap.game_roadmap", game_id=game.id))

    if category not in ("feature", "bug", "improvement"):
        category = "feature"

    # Only devs can choose the initial column; community submissions go to 'planned' You know why
    status = "planned"
    if is_dev:
        requested_status = request.form.get("status", "planned").strip().lower()
        if requested_status in ("planned", "in_progress", "done"):
            status = requested_status

    item = RoadmapItem(
        game_id=game.id,
        author_id=current_user.id,
        title=title[:150],
        description=description or None,
        status=status,
        category=category,
        is_dev_post=is_dev,
        upvotes_count=1,  # author upvotes their own card obviously xD
    )
    db.session.add(item)
    db.session.flush()

    # count that author vote right away (:
    db.session.add(RoadmapVote(item_id=item.id, user_id=current_user.id))

    # poke the dev so they know someone found a bug or has an idea (:
    if not is_dev and game.developer_id != current_user.id:
        db.session.add(Notification(
            user_id=game.developer_id,
            message=f"{current_user.username} submitted a {item.category_label} on '{game.title}': {item.title}",
            type="roadmap_submission"
        ))

    db.session.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
        return jsonify({
            "status": "success",
            "item": {
                "id": item.id,
                "title": item.title,
                "status": item.status,
                "category": item.category,
                "upvotes_count": item.upvotes_count,
            }
        })

    flash(f"'{item.title}' has been added to the board!", "success")
    return redirect(url_for("roadmap.game_roadmap", game_id=game.id))


@roadmap_bp.route("/roadmap/item/<int:item_id>/vote", methods=["POST"])
@login_required
def vote_roadmap_item(item_id):
    item = RoadmapItem.query.get_or_404(item_id)

    existing_vote = RoadmapVote.query.filter_by(item_id=item.id, user_id=current_user.id).first()

    if existing_vote:
        db.session.delete(existing_vote)
        item.upvotes_count = max(0, item.upvotes_count - 1)
        voted = False
    else:
        db.session.add(RoadmapVote(item_id=item.id, user_id=current_user.id))
        item.upvotes_count += 1
        voted = True

    db.session.commit()

    return jsonify({
        "status": "success",
        "voted": voted,
        "upvotes_count": item.upvotes_count
    })


@roadmap_bp.route("/roadmap/item/<int:item_id>/status", methods=["POST"])
@login_required
def update_roadmap_item_status(item_id):
    item = RoadmapItem.query.get_or_404(item_id)
    game = item.game

    is_dev = (current_user.id == game.developer_id) or (getattr(current_user, "role", "") == "admin")
    if not is_dev:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"status": "error", "message": "Only the game developer can change the status."}), 403
        abort(403)

    if request.is_json:
        data = request.get_json() or {}
        new_status = data.get("status", "").strip().lower()
    else:
        new_status = request.form.get("status", "").strip().lower()

    if new_status not in ("planned", "in_progress", "done"):
        return jsonify({"status": "error", "message": "Invalid status."}), 400

    old_status = item.status
    item.status = new_status
    db.session.commit()

    # let the player know the dev actually moved their card (:
    if old_status != new_status and item.author_id != current_user.id:
        db.session.add(Notification(
            user_id=item.author_id,
            message=f"Update on '{game.title}': Your item '{item.title}' is now '{item.status_label}'!",
            type="roadmap_status"
        ))
        db.session.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
        return jsonify({
            "status": "success",
            "new_status": new_status,
            "status_label": item.status_label
        })

    flash(f"Moved '{item.title}' to {item.status_label}.", "success")
    return redirect(url_for("roadmap.game_roadmap", game_id=game.id))


@roadmap_bp.route("/roadmap/item/<int:item_id>/edit", methods=["POST"])
@login_required
def edit_roadmap_item(item_id):
    item = RoadmapItem.query.get_or_404(item_id)
    game = item.game

    is_dev = (current_user.id == game.developer_id) or (getattr(current_user, "role", "") == "admin")
    is_author = (current_user.id == item.author_id)

    if not (is_dev or is_author):
        abort(403)

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    category = request.form.get("category", item.category).strip().lower()

    if not title:
        flash("Title is required.", "error")
        return redirect(url_for("roadmap.game_roadmap", game_id=game.id))

    if category in ("feature", "bug", "improvement"):
        item.category = category

    item.title = title[:150]
    item.description = description or None

    # devs can move status right here too xD
    if is_dev:
        new_status = request.form.get("status", item.status).strip().lower()
        if new_status in ("planned", "in_progress", "done"):
            item.status = new_status

    db.session.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
        return jsonify({
            "status": "success",
            "item": {
                "id": item.id,
                "title": item.title,
                "description": item.description,
                "category": item.category,
                "status": item.status,
            }
        })

    flash(f"Updated '{item.title}'.", "success")
    return redirect(url_for("roadmap.game_roadmap", game_id=game.id))


@roadmap_bp.route("/roadmap/item/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_roadmap_item(item_id):
    item = RoadmapItem.query.get_or_404(item_id)
    game = item.game

    is_dev = (current_user.id == game.developer_id) or (getattr(current_user, "role", "") == "admin")
    is_author = (current_user.id == item.author_id)

    if not (is_dev or is_author):
        abort(403)

    title = item.title
    db.session.delete(item)
    db.session.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
        return jsonify({"status": "success", "message": f"Deleted '{title}'."})

    flash(f"Deleted '{title}'.", "success")
    return redirect(url_for("roadmap.game_roadmap", game_id=game.id))


@roadmap_bp.route("/roadmap/item/<int:item_id>/comment", methods=["POST"])
@login_required
def comment_roadmap_item(item_id):
    item = RoadmapItem.query.get_or_404(item_id)
    game = item.game

    content = request.form.get("content", "").strip()
    if not content and request.is_json:
        content = (request.get_json() or {}).get("content", "").strip()

    if not content:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"status": "error", "message": "Comment cannot be empty."}), 400
        flash("Comment cannot be empty.", "error")
        return redirect(url_for("roadmap.game_roadmap", game_id=game.id))

    comment = RoadmapComment(
        item_id=item.id,
        user_id=current_user.id,
        content=content
    )
    db.session.add(comment)

    # ping author or dev so they see the comment (:
    notify_id = None
    if current_user.id != game.developer_id:
        notify_id = game.developer_id
    elif item.author_id != current_user.id:
        notify_id = item.author_id

    if notify_id:
        db.session.add(Notification(
            user_id=notify_id,
            message=f"{current_user.username} commented on '{item.title}' in {game.title}'s roadmap",
            type="roadmap_comment"
        ))

    db.session.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
        return jsonify({
            "status": "success",
            "comment": {
                "id": comment.id,
                "author": current_user.username,
                "author_is_dev": (current_user.id == game.developer_id),
                "content": comment.content,
                "created_at": comment.created_at.strftime("%d.%m.%Y %H:%M"),
            }
        })

    flash("Comment posted!", "success")
    return redirect(url_for("roadmap.game_roadmap", game_id=game.id))


@roadmap_bp.route("/roadmap/item/<int:item_id>/detail")
def roadmap_item_detail(item_id):
    item = RoadmapItem.query.get_or_404(item_id)
    game = item.game

    is_dev = False
    is_author = False
    has_voted = False

    if current_user.is_authenticated:
        is_dev = (current_user.id == game.developer_id) or (getattr(current_user, "role", "") == "admin")
        is_author = (current_user.id == item.author_id)
        has_voted = RoadmapVote.query.filter_by(item_id=item.id, user_id=current_user.id).first() is not None

    comments_data = []
    for c in item.comments:
        comments_data.append({
            "id": c.id,
            "author": c.user.username,
            "author_is_dev": (c.user_id == game.developer_id),
            "content": c.content,
            "created_at": c.created_at.strftime("%d.%m.%Y %H:%M"),
        })

    return jsonify({
        "id": item.id,
        "title": item.title,
        "description": item.description or "",
        "category": item.category,
        "category_label": item.category_label,
        "status": item.status,
        "status_label": item.status_label,
        "is_dev_post": item.is_dev_post,
        "upvotes_count": item.upvotes_count,
        "author": item.author.username,
        "author_is_dev": (item.author_id == game.developer_id),
        "created_at": item.created_at.strftime("%d.%m.%Y %H:%M"),
        "has_voted": has_voted,
        "can_edit": (is_dev or is_author),
        "can_delete": (is_dev or is_author),
        "is_dev": is_dev,
        "comments": comments_data,
    })

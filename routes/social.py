import os
from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename
from extensions import db
from models.user import User, Friendship, Notification, ProfileComment
from models.game import Game, GameUpdate, UpdateComment, UpdateVote, GameFollow, Review, ReviewVote
from models.commerce import Purchase
from services.file_service import allowed_file
from services.badge_service import (
    sync_user_badges,
    get_user_badges,
    get_featured_badge,
    set_featured_badge,
    get_all_badges,
)
import config

social_bp = Blueprint("social", __name__)


@social_bp.route("/send_friend_request/<int:user_id>")
@login_required
def send_request(user_id):
    #dont want them to spam friend request
    existing = Friendship.query.filter_by(sender_id=current_user.id, receiver_id=user_id).first()
    target_user = db.session.get(User, user_id)
    if not existing and target_user:
        req = Friendship(sender_id=current_user.id, receiver_id=user_id, status="pending")
        db.session.add(req)
        #adding those notifications
        notif = Notification(
            user_id=user_id,
            message=f"{current_user.username} wants to be friends (;",
            type="friend_request"
        )
        db.session.add(notif)
        db.session.commit()
    return redirect(url_for("profile", username=target_user.username))


@social_bp.route("/accept_friend_request/<int:request_id>")
@login_required
def accept_request(request_id):
    req = Friendship.query.get_or_404(request_id)
    if req.receiver_id == current_user.id:
        req.status = "accepted"
        db.session.commit()
        sync_user_badges(current_user)
        if req.sender:
            sync_user_badges(req.sender)
    return redirect(url_for("profile", username=current_user.username))


@social_bp.route("/follow/<username>")
@login_required
def follow(username):
    user = User.query.filter_by(username=username).first()
    if user and user != current_user:
        existing = Friendship.query.filter_by(sender_id=current_user.id, receiver_id=user.id).first()
        if not existing:
            db.session.add(Friendship(sender_id=current_user.id, receiver_id=user.id, status="accepted"))
            db.session.commit()
            sync_user_badges(current_user)
            sync_user_badges(user)
    return redirect(url_for('profile', username=username))


@social_bp.route("/follow_game/<int:game_id>", methods=["POST"])
@login_required
def follow_game(game_id):
    # totally separate from the user Friendship
    # is about getting notified when a specific GAME ships a new update.
    game = Game.query.get_or_404(game_id)
    existing = GameFollow.query.filter_by(user_id=current_user.id, game_id=game.id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({"status": "unfollowed", "following": False})
    else:
        db.session.add(GameFollow(user_id=current_user.id, game_id=game.id))
        db.session.commit()
        return jsonify({"status": "followed", "following": True})


@social_bp.route("/rate_game/<int:game_id>", methods=["POST"])
@login_required
def rate_game(game_id):
    rating = request.form.get("rating")  # "1" for good; "0" for bad
    comment = request.form.get("comment")
    existing = Review.query.filter_by(user_id=current_user.id, game_id=game_id).first()

    if existing:
        existing.is_positive = (rating == "1")
        existing.comment = comment  #update comment
    else:
        # before it compared a String with an Int so it was always false.
        new_review = Review(user_id=current_user.id, game_id=game_id, is_positive=(rating == "1"),
                            comment=comment)

        db.session.add(new_review)

    db.session.commit()
    sync_user_badges(current_user)
    return redirect(url_for("game_detail", game_id=game_id))


@social_bp.route('/unfollow/<username>')
@login_required
def unfollow(username):
    user = User.query.filter_by(username=username).first()
    if user:
        #finding if they are even friends. Better be!
        friendship = Friendship.query.filter(
            ((Friendship.sender_id == current_user.id) & (Friendship.receiver_id == user.id)) |
            ((Friendship.sender_id == user.id) & (Friendship.receiver_id == current_user.id))
        ).first()
        if friendship:
            db.session.delete(friendship)
            db.session.commit()
    return redirect(url_for('profile', username=username))


#clicking twice makes the vote disappear. Pretty basic
@social_bp.route("/vote_review/<int:review_id>/<vote_type>", methods=["POST"])
@login_required
def vote_review(review_id, vote_type):
    if vote_type not in ("helpful", "funny"):
        return "Invalid vote type", 400
    review = Review.query.get_or_404(review_id)

    if review.helpful_count is None:
        review.helpful_count = 0
    if review.funny_count is None:
        review.funny_count = 0

    existing = ReviewVote.query.filter_by(
        review_id=review_id, user_id=current_user.id, vote_type=vote_type
    ).first()
    if existing:
        db.session.delete(existing)
        if vote_type == "helpful":
            review.helpful_count -= 1
        else:
            review.funny_count -= 1
    else:
        db.session.add(ReviewVote(review_id=review_id, user_id=current_user.id, vote_type=vote_type))
        if vote_type == "helpful":
            review.helpful_count += 1
        else:
            review.funny_count += 1

    db.session.commit()
    return jsonify({"helpful": review.helpful_count, "funny": review.funny_count})


#Same toggle idea as vote_review but for GameUpdate posts and up/down.
@social_bp.route("/update/<int:update_id>/vote/<vote_type>", methods=["POST"])
@login_required
def vote_update(update_id, vote_type):
    if vote_type not in ("up", "down"):
        return "Invalid vote type", 400
    update = GameUpdate.query.get_or_404(update_id)

    if update.upvotes is None:
        update.upvotes = 0
    if update.downvotes is None:
        update.downvotes = 0

    existing = UpdateVote.query.filter_by(update_id=update_id, user_id=current_user.id).first()
    if existing:
        if existing.vote_type == vote_type:
            # clicked the same button again removes the vote
            db.session.delete(existing)
            if vote_type == "up":
                update.upvotes -= 1
            else:
                update.downvotes -= 1
        else:
            # switched from up to down or other way around
            if existing.vote_type == "up":
                update.upvotes -= 1
                update.downvotes += 1
            else:
                update.downvotes -= 1
                update.upvotes += 1
            existing.vote_type = vote_type
    else:
        db.session.add(UpdateVote(update_id=update_id, user_id=current_user.id, vote_type=vote_type))
        if vote_type == "up":
            update.upvotes += 1
        else:
            update.downvotes += 1

    db.session.commit()
    return jsonify({"upvotes": update.upvotes, "downvotes": update.downvotes})


@social_bp.route("/update/<int:update_id>/comment", methods=["POST"])
@login_required
def comment_update(update_id):
    update = GameUpdate.query.get_or_404(update_id)
    content = request.form.get("content", "").strip()
    if content:
        db.session.add(UpdateComment(update_id=update.id, user_id=current_user.id, content=content))
        db.session.commit()
    # send them back to wherever they came from
    return redirect(request.referrer or url_for("game_detail", game_id=update.game_id))


@social_bp.route("/update_view/<int:update_id>", methods=["POST"])
def increment_update_view(update_id):
    update = GameUpdate.query.get_or_404(update_id)
    update.view_count += 1
    db.session.commit()
    return jsonify({"status": "success", "views": update.view_count})


@social_bp.route("/updates")
@login_required
def updates_feed():
    tab = request.args.get("tab", "owned")

    owned_game_ids = {
        p.game_id
        for p in Purchase.query.filter_by(user_id=current_user.id, refunded=False).all()
    }

    if tab == "friends":
        friendships = Friendship.query.filter(
            ((Friendship.sender_id == current_user.id) | (Friendship.receiver_id == current_user.id)),
            Friendship.status == "accepted"
        ).all()
        friend_ids = {
            f.receiver_id if f.sender_id == current_user.id else f.sender_id
            for f in friendships
        }
        friend_game_ids = {
            p.game_id
            for p in Purchase.query.filter(
                Purchase.user_id.in_(friend_ids),
                Purchase.refunded == False
            ).all()
        } if friend_ids else set()
        updates = GameUpdate.query.options(db.joinedload(GameUpdate.game)).filter(GameUpdate.game_id.in_(friend_game_ids)) \
            .order_by(GameUpdate.created_at.desc()).all() if friend_game_ids else []

    elif tab == "all":
        updates = GameUpdate.query.options(db.joinedload(GameUpdate.game)).order_by(GameUpdate.created_at.desc()).all()

    else:
        tab = "owned"
        updates = GameUpdate.query.options(db.joinedload(GameUpdate.game)).filter(GameUpdate.game_id.in_(owned_game_ids)) \
            .order_by(GameUpdate.created_at.desc()).all() if owned_game_ids else []

    following_ids = {f.game_id for f in GameFollow.query.filter_by(user_id=current_user.id).all()}
    my_votes = {v.update_id: v.vote_type for v in UpdateVote.query.filter_by(user_id=current_user.id).all()}

    return render_template("updates.html", updates=updates, tab=tab,
                           following_ids=following_ids, my_votes=my_votes)


@social_bp.route("/notification/read/<int:notif_id>")
@login_required
def read_notification(notif_id):
    notif = Notification.query.get_or_404(notif_id)
    #Is it really the notification of the user?
    if notif.user_id == current_user.id:
        notif.is_read = True
        db.session.commit()
    if notif.type == "friend_request":
        sender_name = notif.message.split(" ")[0]
        sender = User.query.filter_by(username=sender_name).first()
        if sender:
            return redirect(url_for('profile', username=sender.username))
    elif notif.type in ["bundle_invite", "bundle_invite_response"]:
        return redirect(url_for('developer_bundles'))
    elif notif.type == "game_update":
        return redirect(url_for('updates_feed'))
    elif notif.type == "gift_received":
        return redirect(url_for('library'))
    elif notif.type == "direct_message":
        # they got mail (: takes them right to the chat
        sender_name = notif.message.split(" ")[0]
        return redirect(url_for("messages.conversation", username=sender_name))
    elif notif.type in ["roadmap_submission", "roadmap_status", "roadmap_comment"]:
        import re
        match = re.search(r"'([^']+)'", notif.message)
        if match:
            from models.game import Game
            game_obj = Game.query.filter_by(title=match.group(1)).first()
            if game_obj:
                return redirect(url_for('roadmap.game_roadmap', game_id=game_obj.id))

    return redirect(url_for("profile", username=current_user.username))


@social_bp.route("/update_profile", methods=["POST"])
@login_required
def update_profile():
    file = request.files.get("profile_pic")
    if file and file.filename != "" and allowed_file(file.filename):
        filename = secure_filename(f"user_{current_user.id}_{file.filename}")
        file.save(os.path.join(config.AVATAR_FOLDER, filename))
        current_user.profile_image = f"avatars/{filename}"
        db.session.commit()
    else:
        return "Not allowed. ONLY PICTURES!", 400
    return redirect(url_for("profile", username=current_user.username))


@social_bp.route("/profile/<username>")
@login_required
def profile(username):
    target_user = User.query.filter_by(username=username).first_or_404()
    # there was some unique bug
    friend_request = Friendship.query.filter(
        ((Friendship.sender_id == current_user.id) & (Friendship.receiver_id == target_user.id)) |
        ((Friendship.sender_id == target_user.id) & (Friendship.receiver_id == current_user.id))
    ).first()

    # newest comments first. Who comes first is last ;)
    comments = ProfileComment.query.options(db.joinedload(ProfileComment.author)) \
        .filter_by(profile_user_id=target_user.id) \
        .order_by(ProfileComment.created_at.desc()).all()

    # Sync and load user badges
    sync_user_badges(target_user)
    badges = get_user_badges(target_user)
    featured_badge = get_featured_badge(target_user)
    all_badges = get_all_badges()

    return render_template(
        "profile.html",
        user=target_user,
        friend_request=friend_request,
        comments=comments,
        badges=badges,
        featured_badge=featured_badge,
        all_badges=all_badges,
    )


@social_bp.route("/profile/feature_badge", methods=["POST"])
@login_required
def feature_badge():
    badge_key = request.form.get("badge_key")
    if badge_key is None and request.is_json:
        badge_key = (request.get_json(silent=True) or {}).get("badge_key")
    success = set_featured_badge(current_user, badge_key)
    if request.is_json:
        return jsonify({
            "status": "success" if success else "error",
            "featured_badge": current_user.featured_badge_key
        })
    return redirect(url_for("profile", username=current_user.username))


@social_bp.route("/profile/<username>/comment", methods=["POST"])
@login_required
def post_profile_comment(username):
    target_user = User.query.filter_by(username=username).first_or_404()

    # respect the owner's setting. We aren't assholes (:
    if not target_user.comments_enabled:
        return "Comments are disabled on this profile", 403

    content = request.form.get("content", "").strip()
    if content:
        new_comment = ProfileComment(
            profile_user_id=target_user.id,
            author_id=current_user.id,
            content=content
        )
        db.session.add(new_comment)

        # notify the profile owner!
        if target_user.id != current_user.id:
            notif = Notification(
                user_id=target_user.id,
                message=f"{current_user.username} commented on your profile",
                type="profile_comment"
            )
            db.session.add(notif)

        db.session.commit()

    return redirect(url_for("profile", username=username))


@social_bp.route("/profile/comment/<int:comment_id>/delete", methods=["POST"])
@login_required
def delete_profile_comment(comment_id):
    comment = ProfileComment.query.get_or_404(comment_id)

    if comment.profile_user_id != current_user.id and comment.author_id != current_user.id:
        return "Access Denied: not your comment or profile", 403

    profile_username = comment.profile_user.username
    db.session.delete(comment)
    db.session.commit()
    return redirect(url_for("profile", username=profile_username))


@social_bp.route("/profile/toggle_comments", methods=["POST"])
@login_required
def toggle_comments():
    current_user.comments_enabled = not current_user.comments_enabled
    db.session.commit()
    return redirect(url_for("profile", username=current_user.username))


@social_bp.route("/community", methods=["GET", "POST"])
def community():
    query = request.form.get("search") if request.method == "POST" else None
    if query:
        users = User.query.filter(User.username.ilike(f"%{query}%")).all()
    else:
        users = User.query.all()

    return render_template("community.html", users=users)

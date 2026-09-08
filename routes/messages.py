from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import current_user, login_required
from sqlalchemy import or_, and_
from extensions import db
from models.user import User, Notification
from models.game import Game
from models.message import DirectMessage

messages_bp = Blueprint("messages", __name__)


# grab all chats for this user (:
def get_user_conversations(user_id):
    # get all dm rows involving us
    all_msgs = DirectMessage.query.filter(
        or_(DirectMessage.sender_id == user_id, DirectMessage.recipient_id == user_id)
    ).order_by(DirectMessage.created_at.desc()).all()

    # sort them by whoever we're gossiping with xD
    seen_users = {}
    conversations = []
    for msg in all_msgs:
        other_id = msg.recipient_id if msg.sender_id == user_id else msg.sender_id
        if other_id not in seen_users:
            other_user = db.session.get(User, other_id)
            if not other_user:
                continue
            unread_count = DirectMessage.query.filter_by(
                sender_id=other_id,
                recipient_id=user_id,
                is_read=False
            ).count()
            conv = {
                "user": other_user,
                "latest_message": msg,
                "unread_count": unread_count,
            }
            seen_users[other_id] = conv
            conversations.append(conv)
    return conversations


# message hub (:
@messages_bp.route("/messages")
@login_required
def inbox():
    conversations = get_user_conversations(current_user.id)
    target_username = request.args.get("to")
    game_id = request.args.get("game_id", type=int)

    active_game = db.session.get(Game, game_id) if game_id else None

    if target_username:
        active_partner = User.query.filter_by(username=target_username).first()
        if active_partner and active_partner.id != current_user.id:
            return redirect(url_for("messages.conversation", username=active_partner.username, game_id=game_id))

    # open first chat so user doesn't stare into the void (:
    if conversations:
        first_user = conversations[0]["user"]
        return redirect(url_for("messages.conversation", username=first_user.username))

    return render_template(
        "messages.html",
        conversations=conversations,
        active_partner=None,
        messages=[],
        active_game=active_game
    )


# chatting with someone specific (:
@messages_bp.route("/messages/<username>")
@login_required
def conversation(username):
    target_user = User.query.filter_by(username=username).first_or_404()
    if target_user.id == current_user.id:
        flash("You cannot chat with yourself (: Try messaging someone else.", "error")
        return redirect(url_for("messages.inbox"))

    game_id = request.args.get("game_id", type=int)
    active_game = db.session.get(Game, game_id) if game_id else None

    # marked as read, no more unread badges (:
    DirectMessage.query.filter_by(
        sender_id=target_user.id,
        recipient_id=current_user.id,
        is_read=False
    ).update({"is_read": True})

    # clear the bell notifications too
    notifs = Notification.query.filter_by(
        user_id=current_user.id,
        type="direct_message",
        is_read=False
    ).all()
    for n in notifs:
        if n.message.startswith(f"{target_user.username} "):
            n.is_read = True
    db.session.commit()

    # load the whole drama history xD
    chat_messages = DirectMessage.query.filter(
        or_(
            and_(DirectMessage.sender_id == current_user.id, DirectMessage.recipient_id == target_user.id),
            and_(DirectMessage.sender_id == target_user.id, DirectMessage.recipient_id == current_user.id)
        )
    ).order_by(DirectMessage.created_at.asc()).all()

    conversations = get_user_conversations(current_user.id)

    # put them in the sidebar even if we havent said hi yet (:
    if not any(c["user"].id == target_user.id for c in conversations):
        conversations.insert(0, {
            "user": target_user,
            "latest_message": None,
            "unread_count": 0
        })

    return render_template(
        "messages.html",
        conversations=conversations,
        active_partner=target_user,
        messages=chat_messages,
        active_game=active_game
    )


# send message go zoom (:
@messages_bp.route("/messages/send", methods=["POST"])
@login_required
def send_message():
    recipient_id = request.form.get("recipient_id", type=int)
    content = request.form.get("content", "").strip()
    game_id = request.form.get("game_id", type=int)

    if not content:
        flash("Message cannot be empty.", "error")
        return redirect(request.referrer or url_for("messages.inbox"))

    recipient = db.session.get(User, recipient_id) if recipient_id else None
    if not recipient or recipient.id == current_user.id:
        flash("Invalid recipient.", "error")
        return redirect(url_for("messages.inbox"))

    # save text to db
    new_msg = DirectMessage(
        sender_id=current_user.id,
        recipient_id=recipient.id,
        content=content,
        game_id=game_id
    )
    db.session.add(new_msg)

    # ring the bell for the other person (:
    notif = Notification(
        user_id=recipient.id,
        message=f"{current_user.username} sent you a message",
        type="direct_message"
    )
    db.session.add(notif)
    db.session.commit()

    if request.is_json:
        return jsonify({
            "status": "success",
            "message_id": new_msg.id,
            "content": new_msg.content,
            "created_at": new_msg.created_at.strftime("%H:%M")
        })

    return redirect(url_for("messages.conversation", username=recipient.username))


# wipe message out of existence xD
@messages_bp.route("/messages/delete/<int:message_id>", methods=["POST"])
@login_required
def delete_message(message_id):
    msg = DirectMessage.query.get_or_404(message_id)
    if msg.sender_id != current_user.id and msg.recipient_id != current_user.id:
        return "Access Denied", 403

    other_user = msg.recipient if msg.sender_id == current_user.id else msg.sender
    db.session.delete(msg)
    db.session.commit()
    return redirect(url_for("messages.conversation", username=other_user.username))


# how many unread dms we got (:
@messages_bp.route("/messages/unread_count")
@login_required
def unread_count():
    count = DirectMessage.query.filter_by(
        recipient_id=current_user.id,
        is_read=False
    ).count()
    return jsonify({"unread_count": count})

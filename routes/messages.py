from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import current_user, login_required
from flask_socketio import emit, join_room, leave_room
from sqlalchemy import or_, and_
from extensions import db, socketio
from models.user import User, Notification
from models.game import Game
from models.message import DirectMessage
from models.card import CardTrade
from services.card_service import (
    propose_trade,
    execute_trade_action,
    get_user_duplicates,
    get_all_card_definitions,
    get_card_definition,
)

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

    user_duplicates = get_user_duplicates(current_user.id)
    all_cards = get_all_card_definitions()

    return render_template(
        "messages.html",
        conversations=conversations,
        active_partner=target_user,
        messages=chat_messages,
        active_game=active_game,
        user_duplicates=user_duplicates,
        all_cards=all_cards,
        get_card_definition=get_card_definition,
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

    unread_count = DirectMessage.query.filter_by(
        recipient_id=recipient.id,
        is_read=False
    ).count()

    payload = {
        "id": new_msg.id,
        "sender_id": current_user.id,
        "sender_username": current_user.username,
        "sender_avatar": url_for("static", filename=current_user.profile_image),
        "recipient_id": recipient.id,
        "recipient_username": recipient.username,
        "content": new_msg.content,
        "game_id": new_msg.game_id,
        "game_title": new_msg.game.title if new_msg.game else None,
        "created_at": new_msg.created_at.strftime('%d.%m %H:%M'),
        "time": new_msg.created_at.strftime('%H:%M'),
        "is_read": False,
    }
    socketio.emit("new_message", payload, room=f"user_{recipient.id}")
    socketio.emit("unread_count_update", {"unread_count": unread_count}, room=f"user_{recipient.id}")

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
    s_id = msg.sender_id
    r_id = msg.recipient_id
    db.session.delete(msg)
    db.session.commit()
    socketio.emit("message_deleted", {"message_id": message_id}, room=f"user_{s_id}")
    socketio.emit("message_deleted", {"message_id": message_id}, room=f"user_{r_id}")
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


# propose card trade to homie (:
@messages_bp.route("/messages/trade/propose", methods=["POST"])
@login_required
def trade_propose():
    recipient_id = request.form.get("recipient_id", type=int)
    offered_card_key = request.form.get("offered_card_key", "").strip()
    requested_card_key = request.form.get("requested_card_key", "").strip() or None
    note = request.form.get("note", "").strip() or None

    recipient = db.session.get(User, recipient_id) if recipient_id else None
    if not recipient or recipient.id == current_user.id:
        flash("Invalid recipient for trade proposal.", "error")
        return redirect(url_for("messages.inbox"))

    success, msg, _ = propose_trade(
        sender_id=current_user.id,
        receiver_id=recipient.id,
        offered_card_key=offered_card_key,
        requested_card_key=requested_card_key,
        note=note,
    )

    if success:
        flash(f"[TRADE PROPOSAL] {msg}", "success")
    else:
        flash(f"[TRADE ERROR] {msg}", "error")

    return redirect(url_for("messages.conversation", username=recipient.username))


# accept homie trade (:
@messages_bp.route("/messages/trade/<int:trade_id>/accept", methods=["POST"])
@login_required
def trade_accept(trade_id):
    success, msg = execute_trade_action(trade_id, current_user.id, action="accept")
    if success:
        flash(f"[TRADE SUCCESS] {msg}", "success")
    else:
        flash(f"[TRADE ERROR] {msg}", "error")
    return redirect(request.referrer or url_for("messages.inbox"))


# decline trade (:
@messages_bp.route("/messages/trade/<int:trade_id>/decline", methods=["POST"])
@login_required
def trade_decline(trade_id):
    success, msg = execute_trade_action(trade_id, current_user.id, action="decline")
    if success:
        flash(f"[TRADE] {msg}", "info")
    else:
        flash(f"[TRADE ERROR] {msg}", "error")
    return redirect(request.referrer or url_for("messages.inbox"))


# cancel pending trade offer (:
@messages_bp.route("/messages/trade/<int:trade_id>/cancel", methods=["POST"])
@login_required
def trade_cancel(trade_id):
    success, msg = execute_trade_action(trade_id, current_user.id, action="cancel")
    if success:
        flash(f"[TRADE] {msg}", "info")
    else:
        flash(f"[TRADE ERROR] {msg}", "error")
    return redirect(request.referrer or url_for("messages.inbox"))


# -------------------------------------------------------------------------
# WebSocket Real-Time Handlers
# -------------------------------------------------------------------------

@socketio.on("connect")
def handle_socket_connect():
    if current_user.is_authenticated:
        join_room(f"user_{current_user.id}")


@socketio.on("send_direct_message")
def handle_socket_send_message(data):
    if not current_user.is_authenticated:
        return {"status": "error", "error": "Unauthorized"}

    recipient_id = data.get("recipient_id")
    try:
        recipient_id = int(recipient_id) if recipient_id is not None else None
    except (ValueError, TypeError):
        return {"status": "error", "error": "Invalid recipient."}

    content = (data.get("content") or "").strip()
    game_id = data.get("game_id")
    try:
        game_id = int(game_id) if game_id is not None else None
    except (ValueError, TypeError):
        game_id = None

    if not content:
        return {"status": "error", "error": "Message cannot be empty."}

    recipient = db.session.get(User, recipient_id) if recipient_id else None
    if not recipient or recipient.id == current_user.id:
        return {"status": "error", "error": "Invalid recipient."}

    new_msg = DirectMessage(
        sender_id=current_user.id,
        recipient_id=recipient.id,
        content=content,
        game_id=game_id
    )
    db.session.add(new_msg)

    notif = Notification(
        user_id=recipient.id,
        message=f"{current_user.username} sent you a message",
        type="direct_message"
    )
    db.session.add(notif)
    db.session.commit()

    unread_count = DirectMessage.query.filter_by(
        recipient_id=recipient.id,
        is_read=False
    ).count()

    payload = {
        "id": new_msg.id,
        "sender_id": current_user.id,
        "sender_username": current_user.username,
        "sender_avatar": url_for("static", filename=current_user.profile_image),
        "recipient_id": recipient.id,
        "recipient_username": recipient.username,
        "content": new_msg.content,
        "game_id": new_msg.game_id,
        "game_title": new_msg.game.title if new_msg.game else None,
        "created_at": new_msg.created_at.strftime('%d.%m %H:%M'),
        "time": new_msg.created_at.strftime('%H:%M'),
        "is_read": False,
    }

    emit("new_message", payload, room=f"user_{recipient.id}")
    emit("unread_count_update", {"unread_count": unread_count}, room=f"user_{recipient.id}")
    emit("message_sent", payload, room=f"user_{current_user.id}")

    return {"status": "success", "message": payload}


@socketio.on("mark_read")
def handle_socket_mark_read(data):
    if not current_user.is_authenticated:
        return
    sender_id = data.get("sender_id")
    try:
        sender_id = int(sender_id) if sender_id is not None else None
    except (ValueError, TypeError):
        return

    if not sender_id:
        return

    DirectMessage.query.filter_by(
        sender_id=sender_id,
        recipient_id=current_user.id,
        is_read=False
    ).update({"is_read": True})

    sender_user = db.session.get(User, sender_id)
    if sender_user:
        notifs = Notification.query.filter_by(
            user_id=current_user.id,
            type="direct_message",
            is_read=False
        ).all()
        for n in notifs:
            if n.message.startswith(f"{sender_user.username} "):
                n.is_read = True
    db.session.commit()

    emit("messages_read", {"reader_id": current_user.id, "sender_id": sender_id}, room=f"user_{sender_id}")

    unread_count = DirectMessage.query.filter_by(
        recipient_id=current_user.id,
        is_read=False
    ).count()
    emit("unread_count_update", {"unread_count": unread_count}, room=f"user_{current_user.id}")


@socketio.on("delete_message")
def handle_socket_delete_message(data):
    if not current_user.is_authenticated:
        return {"status": "error", "error": "Unauthorized"}
    msg_id = data.get("message_id")
    try:
        msg_id = int(msg_id) if msg_id is not None else None
    except (ValueError, TypeError):
        return {"status": "error", "error": "Invalid message ID"}

    msg = db.session.get(DirectMessage, msg_id) if msg_id else None
    if not msg:
        return {"status": "error", "error": "Message not found"}
    if msg.sender_id != current_user.id and msg.recipient_id != current_user.id:
        return {"status": "error", "error": "Access denied"}

    s_id = msg.sender_id
    r_id = msg.recipient_id
    db.session.delete(msg)
    db.session.commit()

    emit("message_deleted", {"message_id": msg_id}, room=f"user_{s_id}")
    emit("message_deleted", {"message_id": msg_id}, room=f"user_{r_id}")
    return {"status": "success"}


@socketio.on("typing")
def handle_socket_typing(data):
    if not current_user.is_authenticated:
        return
    recipient_id = data.get("recipient_id")
    try:
        recipient_id = int(recipient_id) if recipient_id is not None else None
    except (ValueError, TypeError):
        return
    if recipient_id:
        emit("user_typing", {
            "user_id": current_user.id,
            "username": current_user.username
        }, room=f"user_{recipient_id}")


@socketio.on("stop_typing")
def handle_socket_stop_typing(data):
    if not current_user.is_authenticated:
        return
    recipient_id = data.get("recipient_id")
    try:
        recipient_id = int(recipient_id) if recipient_id is not None else None
    except (ValueError, TypeError):
        return
    if recipient_id:
        emit("user_stop_typing", {
            "user_id": current_user.id,
            "username": current_user.username
        }, room=f"user_{recipient_id}")

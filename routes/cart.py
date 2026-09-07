import json
import stripe
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, flash, session
from flask_login import current_user, login_required
from extensions import db, limiter
from models.game import Game
from models.commerce import Purchase, CartItem
from services.game_service import calculate_display_price
from services.cart_service import (
    _generate_cart_token,
    _valid_cart_token,
    _compute_bundle_alerts,
)
from services.payment_service import fulfill_checkout
import config

cart_bp = Blueprint("cart", __name__)


# ---------------------------------------------------------------------------
# Cart system
# ---------------------------------------------------------------------------


@cart_bp.route("/cart/add/<int:game_id>", methods=["POST"])
@limiter.limit("60/hour")
def cart_add(game_id):
    #  JS must pass the HMAC nonce we embed in the page. Bots shall fall
    if not _valid_cart_token(request):
        return jsonify(error="Invalid request"), 400

    game = db.session.get(Game, game_id)
    if not game:
        return jsonify(error="Game not found"), 404

    if current_user.is_authenticated:
        already_owns = Purchase.query.filter_by(
            user_id=current_user.id, game_id=game_id, refunded=False
        ).first()
        if already_owns:
            return jsonify(error="You already own this game"), 400
        existing = CartItem.query.filter_by(
            user_id=current_user.id, game_id=game_id
        ).first()
        if not existing:
            db.session.add(CartItem(user_id=current_user.id, game_id=game_id))
            db.session.commit()
        cart_count = CartItem.query.filter_by(user_id=current_user.id).count()
    else:
        guest_cart = session.get("guest_cart", [])
        if game_id not in guest_cart:
            guest_cart.append(game_id)
            session["guest_cart"] = guest_cart
            session.modified = True
        cart_count = len(session.get("guest_cart", []))

    return jsonify(in_cart=True, cart_count=cart_count)


@cart_bp.route("/cart/remove/<int:game_id>", methods=["POST"])
def cart_remove(game_id):
    if current_user.is_authenticated:
        CartItem.query.filter_by(user_id=current_user.id, game_id=game_id).delete()
        db.session.commit()
        cart_count = CartItem.query.filter_by(user_id=current_user.id).count()
    else:
        guest_cart = session.get("guest_cart", [])
        if game_id in guest_cart:
            guest_cart.remove(game_id)
            session["guest_cart"] = guest_cart
            session.modified = True
        cart_count = len(session.get("guest_cart", []))
    return jsonify(in_cart=False, cart_count=cart_count)


@cart_bp.route("/cart")
def cart_view():
    if current_user.is_authenticated:
        owned_ids = {
            p.game_id
            for p in Purchase.query.filter_by(user_id=current_user.id, refunded=False).all()
        }
        # Silently drop stale items (games now owned via other means)
        stale = CartItem.query.filter(
            CartItem.user_id == current_user.id,
            CartItem.game_id.in_(owned_ids)
        ).all()
        for item in stale:
            db.session.delete(item)
        if stale:
            db.session.commit()

        items = CartItem.query.filter_by(user_id=current_user.id).order_by(CartItem.added_at.desc()).all()
        cart_games = []
        for item in items:
            g = item.game
            g.display_price = calculate_display_price(g)
            cart_games.append(g)
    else:
        guest_cart = session.get("guest_cart", [])
        owned_ids = set()
        games_list = Game.query.filter(Game.id.in_(guest_cart)).all() if guest_cart else []
        cart_games = []
        for g in games_list:
            g.display_price = calculate_display_price(g)
            cart_games.append(g)

    cart_total = round(sum(g.display_price for g in cart_games), 2)
    cart_game_ids = [g.id for g in cart_games]
    bundle_alerts = _compute_bundle_alerts(cart_game_ids, owned_ids)
    cart_token = _generate_cart_token()

    return render_template(
        "cart.html",
        cart_games=cart_games,
        cart_total=cart_total,
        bundle_alerts=bundle_alerts,
        cart_token=cart_token,
    )


@cart_bp.route("/create-cart-checkout-session")
@login_required
def create_cart_checkout_session():
    if not config.stripe_keys["secret_key"]:
        return jsonify(error="Stripe is not configured"), 500

    items = CartItem.query.filter_by(user_id=current_user.id).all()
    if not items:
        return jsonify(error="Your cart is empty"), 400

    owned_ids = {
        p.game_id
        for p in Purchase.query.filter_by(user_id=current_user.id, refunded=False).all()
    }
    games = [item.game for item in items if item.game_id not in owned_ids]
    if not games:
        return jsonify(error="You already own all games in your cart"), 400

    for g in games:
        g.display_price = calculate_display_price(g)

    stripe.api_key = config.stripe_keys["secret_key"]
    line_items = [
        {
            "price_data": {
                "currency": "eur",
                "product_data": {"name": g.title},
                "unit_amount": int(round(g.display_price * 100)),
            },
            "quantity": 1,
        }
        for g in games
    ]

    try:
        checkout_session = stripe.checkout.Session.create(
            success_url=(
                url_for("cart_success", _external=True)
                + "?session_id={CHECKOUT_SESSION_ID}"
            ),
            cancel_url=url_for("cart_view", _external=True),
            payment_method_types=["card"],
            mode="payment",
            client_reference_id=str(current_user.id),
            metadata={
                "user_id": str(current_user.id),
                "cart_game_ids": json.dumps([g.id for g in games]),
            },
            payment_intent_data={
                "transfer_group": f"cart_{current_user.id}_{int(round(sum(g.display_price for g in games) * 100))}",
            },
            line_items=line_items,
        )
        return jsonify({"sessionId": checkout_session.id})
    except stripe.error.StripeError as e:
        print(f"DEBUG: Stripe cart checkout error: {e}")
        return jsonify(error="Could not create Stripe checkout session"), 500


@cart_bp.route("/cart_success")
@login_required
def cart_success():
    session_id = request.args.get("session_id")
    if not session_id:
        flash("Missing Stripe checkout session.", "error")
        return redirect(url_for("cart_view"))

    try:
        stripe.api_key = config.stripe_keys["secret_key"]
        checkout_session = stripe.checkout.Session.retrieve(session_id)

        if checkout_session.client_reference_id != str(current_user.id):
            flash("This payment session does not belong to your account.", "error")
            return redirect(url_for("cart_view"))

        if checkout_session.payment_status != "paid":
            flash("Payment has not been completed yet.", "error")
            return redirect(url_for("cart_view"))

        fulfilled = fulfill_checkout(checkout_session.id)

        if fulfilled:
            CartItem.query.filter_by(user_id=current_user.id).delete()
            db.session.commit()
        else:
            flash("Payment was successful, but some games could not be added yet.", "error")

    except stripe.error.StripeError as e:
        print(f"DEBUG: Could not verify cart success session: {e}")
        flash("The payment could not be verified.", "error")
    except Exception as e:
        print(f"DEBUG: Cart success error: {e}")
        flash("Something went wrong while adding games to your library.", "error")

    return render_template("cart_success.html")

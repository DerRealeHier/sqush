from datetime import datetime, timezone
import stripe
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, flash
from flask_login import current_user, login_required
from extensions import db
from models.user import User, Notification
from models.game import Game
from models.commerce import Purchase, Gift, Tip
from models.bundle import Bundle
from services.game_service import calculate_display_price, update_daily_stats
from services.payment_service import (
    fulfill_checkout,
    fulfill_gift,
    fulfill_tip,
    _extract_metadata,
    calculate_payout_split,
    process_pending_payouts_for_developer,
)
import config

checkout_bp = Blueprint("checkout", __name__)


@checkout_bp.route("/create-checkout-session/<int:game_id>")
@login_required
def create_checkout_session(game_id):
    game = Game.query.get_or_404(game_id)

    # Never start another checkout when the user already owns the game.
    existing_purchase = Purchase.query.filter_by(
        user_id=current_user.id,
        game_id=game.id
    ).first()

    if existing_purchase and not existing_purchase.refunded:
        return jsonify(error="You already own this game"), 400

    if not config.stripe_keys["secret_key"]:
        return jsonify(error="Stripe is not configured"), 500

    stripe.api_key = config.stripe_keys["secret_key"]

    display_price = calculate_display_price(game)
    unit_amount = int(round(display_price * 100))

    try:
        session_params = {
            "success_url": (
                url_for("success", game_id=game.id, _external=True)
                + "?session_id={CHECKOUT_SESSION_ID}"
            ),
            "cancel_url": url_for("game_detail", game_id=game.id, _external=True),
            "payment_method_types": ["card"],
            "mode": "payment",
            "client_reference_id": str(current_user.id),
            "metadata": {
                "user_id": str(current_user.id),
                "game_id": str(game.id),
            },
            "line_items": [
                {
                    "price_data": {
                        "currency": "eur",
                        "product_data": {
                            "name": game.title,
                        },
                        "unit_amount": unit_amount,
                    },
                    "quantity": 1,
                }
            ],
        }

        # Automated Dev Payout: If dev has Stripe Connect with payouts enabled, split automatically!
        dev_user = game.user
        if dev_user and dev_user.stripe_connect_id and dev_user.stripe_connect_payouts_enabled and unit_amount > 0:
            split = calculate_payout_split(display_price)
            fee_cents = split["platform_fee_cents"]
            session_params["payment_intent_data"] = {
                "application_fee_amount": fee_cents,
                "transfer_data": {
                    "destination": dev_user.stripe_connect_id,
                },
            }
            session_params["metadata"]["is_destination_charge"] = "true"

        checkout_session = stripe.checkout.Session.create(**session_params)

        return jsonify({"sessionId": checkout_session.id})

    except stripe.error.StripeError as e:
        print(f"DEBUG: Stripe checkout error: {e}")
        return jsonify(error="Could not create Stripe checkout session"), 500
    except Exception as e:
        print(f"DEBUG: Checkout error: {e}")
        return jsonify(error="Could not create checkout session"), 500


# -------------------------------------------------------------------------
# Gift routes
# -------------------------------------------------------------------------

@checkout_bp.route("/gift/<int:game_id>")
@login_required
def gift_page(game_id):
    # show the gifting form
    game = Game.query.get_or_404(game_id)
    game.display_price = calculate_display_price(game)
    return render_template("gift.html", game=game)


@checkout_bp.route("/create-gift-checkout-session/<int:game_id>", methods=["POST"])
@login_required
def create_gift_checkout_session(game_id):
    # validate the recipient then create the checkout session
    game = Game.query.get_or_404(game_id)

    payload = request.get_json(silent=True) or {}
    recipient_username = payload.get("recipient_username", "").strip()
    gift_message = payload.get("message", "").strip()[:500]

    if not recipient_username:
        return jsonify(error="Please enter a username"), 400

    recipient = User.query.filter_by(username=recipient_username).first()
    if not recipient:
        return jsonify(error="User not found"), 404

    if recipient.id == current_user.id:
        return jsonify(error="You can't gift a game to yourself"), 400

    already_owns = Purchase.query.filter_by(
        user_id=recipient.id, game_id=game.id, refunded=False
    ).first()
    if already_owns:
        return jsonify(error=f"{recipient.username} already owns this game"), 400

    display_price = calculate_display_price(game)
    unit_amount = int(round(display_price * 100))

    if unit_amount <= 0:
        # Free game direct gift
        p = Purchase(
            user_id=recipient.id,
            game_id=game.id,
            price_paid=0.0,
            refunded=False,
        )
        db.session.add(p)
        gift = Gift(
            sender_id=current_user.id,
            recipient_id=recipient.id,
            game_id=game.id,
            message=gift_message,
        )
        db.session.add(gift)
        notif_msg = f"{current_user.username} gifted you '{game.title}'!"
        if gift_message:
            notif_msg += f' "{gift_message[:100]}"'
        db.session.add(Notification(
            user_id=recipient.id,
            message=notif_msg,
            type="gift_received",
        ))
        db.session.commit()
        update_daily_stats(game)
        return jsonify({"redirect": url_for("gift_success", game_id=game.id)})

    if not config.stripe_keys["secret_key"]:
        return jsonify(error="Stripe is not configured"), 500

    stripe.api_key = config.stripe_keys["secret_key"]

    try:
        session_params = {
            "success_url": (
                url_for("gift_success", game_id=game.id, _external=True)
                + "?session_id={CHECKOUT_SESSION_ID}"
            ),
            "cancel_url": url_for("gift_page", game_id=game.id, _external=True),
            "payment_method_types": ["card"],
            "mode": "payment",
            "client_reference_id": str(current_user.id),
            "metadata": {
                "purchase_type": "gift",
                "user_id":       str(current_user.id),   # sender (pays)
                "recipient_id":  str(recipient.id),       # recipient (gets the game)
                "game_id":       str(game.id),
                "gift_message":  gift_message,
            },
            "line_items": [{
                "price_data": {
                    "currency": "eur",
                    "product_data": {
                        "name": f"{game.title} - Gift for {recipient.username}",
                    },
                    "unit_amount": unit_amount,
                },
                "quantity": 1,
            }],
        }

        # Automated Dev Payout for gift purchases
        dev_user = game.user
        if dev_user and dev_user.stripe_connect_id and dev_user.stripe_connect_payouts_enabled and unit_amount > 0:
            split = calculate_payout_split(unit_amount / 100.0)
            fee_cents = split["platform_fee_cents"]
            session_params["payment_intent_data"] = {
                "application_fee_amount": fee_cents,
                "transfer_data": {
                    "destination": dev_user.stripe_connect_id,
                },
            }
            session_params["metadata"]["is_destination_charge"] = "true"

        checkout_session = stripe.checkout.Session.create(**session_params)
        return jsonify({"sessionId": checkout_session.id})
    except stripe.error.StripeError as e:
        print(f"DEBUG: Stripe gift checkout error: {e}")
        return jsonify(error="Could not create Stripe checkout session"), 500


@checkout_bp.route("/gift_success/<int:game_id>")
@login_required
def gift_success(game_id):
    """Fallback success page: called after Stripe redirects the sender back."""
    game = Game.query.get_or_404(game_id)
    session_id = request.args.get("session_id")

    recipient_name = None

    if not session_id:
        # Check if a recent gift was just created for this game by current_user
        recent_gift = Gift.query.filter_by(sender_id=current_user.id, game_id=game.id).order_by(Gift.sent_at.desc()).first()
        if recent_gift and (datetime.now(timezone.utc) - recent_gift.sent_at.replace(tzinfo=timezone.utc)).total_seconds() < 60:
            recipient_name = recent_gift.recipient.username
            flash(f"Gift sent! {recipient_name} now has '{game.title}' in their library.", "success")
            return render_template("gift_success.html", game=game, recipient_name=recipient_name)
        flash("Missing Stripe checkout session.", "error")
        return redirect(url_for("gift_page", game_id=game.id))

    try:
        stripe.api_key = config.stripe_keys["secret_key"]
        checkout_session = stripe.checkout.Session.retrieve(session_id)

        if checkout_session.client_reference_id != str(current_user.id):
            flash("This payment session does not belong to your account.", "error")
            return redirect(url_for("gift_page", game_id=game.id))

        if checkout_session.payment_status != "paid":
            flash("Payment has not been completed yet.", "error")
            return redirect(url_for("gift_page", game_id=game.id))

        # Idempotent: webhook may have already run this, that's fine
        fulfilled = fulfill_gift(checkout_session.id)

        #now the Stripe metadata shouldn't be touched
        gift_record = Gift.query.filter_by(
            stripe_checkout_session_id=checkout_session.id
        ).first()
        if gift_record:
            recipient_name = gift_record.recipient.username

        if fulfilled:
            flash(
                f"Gift sent! {recipient_name or 'Your friend'} "
                f"now has '{game.title}' in their library.",
                "success",
            )
        else:
            flash(
                "Payment was successful, but the gift could not be processed yet. "
                "The recipient will receive the game shortly.",
                "warning",
            )

    except stripe.error.StripeError as e:
        print(f"DEBUG: Could not verify gift success session: {e}")
        flash("The payment could not be verified.", "error")
    except Exception as e:
        print(f"DEBUG: Gift success error: {e}")
        flash("Something went wrong while processing the gift.", "error")

    return render_template("gift_success.html", game=game, recipient_name=recipient_name)


# -------------------------------------------------------------------------
# Tip Jar routes
# -------------------------------------------------------------------------

@checkout_bp.route("/create-tip-checkout-session/<int:game_id>", methods=["POST"])
def create_tip_checkout_session(game_id):
    # throw extra cash at the dev (:
    game = Game.query.get_or_404(game_id)

    if current_user.is_authenticated and current_user.id == game.developer_id:
        return jsonify(error="You cannot tip your own game! Nice try (:"), 400

    payload = request.get_json(silent=True) or {}
    try:
        amount = float(payload.get("amount", 0))
    except (ValueError, TypeError):
        return jsonify(error="Please enter a valid amount."), 400

    if amount < 1.00:
        return jsonify(error="The minimum tip amount is 1.00 €."), 400
    if amount > 500.00:
        return jsonify(error="The maximum tip amount is 500.00 €."), 400

    message = (payload.get("message") or "").strip()[:500]
    supporter_name = (payload.get("supporter_name") or "").strip()[:64]
    if current_user.is_authenticated:
        supporter_name = current_user.username
    elif not supporter_name:
        supporter_name = "Anonymous Fan"

    if not config.stripe_keys["secret_key"]:
        return jsonify(error="Stripe is not configured"), 500

    stripe.api_key = config.stripe_keys["secret_key"]
    unit_amount = int(round(amount * 100))

    try:
        user_id_str = str(current_user.id) if current_user.is_authenticated else ""
        dev_username = game.user.username if game.user else "Developer"
        session_params = {
            "success_url": (
                url_for("checkout.tip_success", game_id=game.id, _external=True)
                + "?session_id={CHECKOUT_SESSION_ID}"
            ),
            "cancel_url": url_for("game_detail", game_id=game.id, _external=True),
            "payment_method_types": ["card"],
            "mode": "payment",
            "client_reference_id": user_id_str,
            "metadata": {
                "purchase_type": "tip",
                "user_id": user_id_str,
                "developer_id": str(game.developer_id),
                "game_id": str(game.id),
                "tip_amount": f"{amount:.2f}",
                "tip_message": message,
                "supporter_name": supporter_name,
            },
            "line_items": [{
                "price_data": {
                    "currency": "eur",
                    "product_data": {
                        "name": f"Tip Jar: Tip for {dev_username} ({game.title})",
                    },
                    "unit_amount": unit_amount,
                },
                "quantity": 1,
            }],
        }

        # Automated Dev Payout for tips
        dev_user = game.user
        if dev_user and dev_user.stripe_connect_id and dev_user.stripe_connect_payouts_enabled and unit_amount > 0:
            split = calculate_payout_split(amount, is_tip=True)
            fee_cents = split["platform_fee_cents"]
            session_params["payment_intent_data"] = {
                "application_fee_amount": fee_cents,
                "transfer_data": {
                    "destination": dev_user.stripe_connect_id,
                },
            }
            session_params["metadata"]["is_destination_charge"] = "true"

        checkout_session = stripe.checkout.Session.create(**session_params)
        return jsonify({"sessionId": checkout_session.id})
    except stripe.error.StripeError as e:
        print(f"DEBUG: Stripe tip error: {e}")
        return jsonify(error="Failed to create Stripe checkout session"), 500
    except Exception as e:
        print(f"DEBUG: Tip checkout error: {e}")
        return jsonify(error="Error creating checkout session"), 500


@checkout_bp.route("/tip_success/<int:game_id>")
def tip_success(game_id):
    # dev got their cash, back to the game page (:
    game = Game.query.get_or_404(game_id)
    session_id = request.args.get("session_id")

    if not session_id:
        flash("Missing Stripe session.", "error")
        return redirect(url_for("game_detail", game_id=game.id))

    try:
        stripe.api_key = config.stripe_keys["secret_key"]
        checkout_session = stripe.checkout.Session.retrieve(session_id)

        if checkout_session.payment_status != "paid":
            flash("Payment has not been completed yet.", "warning")
            return redirect(url_for("game_detail", game_id=game.id))

        fulfilled = fulfill_tip(checkout_session.id)
        tip_record = Tip.query.filter_by(
            stripe_checkout_session_id=checkout_session.id
        ).first()

        dev_name = game.user.username if game.user else "the developer"
        amount_str = f"{tip_record.amount:.2f}€" if tip_record else "your tip"

        if fulfilled:
            flash(
                f"Your tip of {amount_str} was sent directly to {dev_name}. Thanks for your support! (:",
                "success",
            )
        else:
            flash(
                "Payment was successful! Your tip will be credited shortly.",
                "info",
            )
    except Exception as e:
        print(f"DEBUG: Tip success error: {e}")
        flash("Thank you for your support!", "success")

    return redirect(url_for("game_detail", game_id=game.id))


@checkout_bp.route("/create-bundle-checkout-session/<int:bundle_id>")
@login_required
def create_bundle_checkout_session(bundle_id):
    bundle = Bundle.query.get_or_404(bundle_id)
    if not bundle.is_published:
        return jsonify(error="Bundle is not available"), 400

    if not config.stripe_keys["secret_key"]:
        return jsonify(error="Stripe is not configured"), 500

    stripe.api_key = config.stripe_keys["secret_key"]
    display_price = bundle.display_price
    unit_amount = int(round(display_price * 100))

    try:
        checkout_session = stripe.checkout.Session.create(
            success_url=(url_for("bundle_success", bundle_id=bundle.id, _external=True) + "?session_id={CHECKOUT_SESSION_ID}"),
            cancel_url=url_for("bundle_detail", bundle_id=bundle.id, _external=True),
            payment_method_types=["card"],
            mode="payment",
            client_reference_id=str(current_user.id),
            # ITS A BUNDLE ID!!!!!!!!!!!! Please dont forget this (me)
            metadata={"user_id": str(current_user.id), "bundle_id": str(bundle.id)},
            line_items=[{"price_data": {"currency": "eur", "product_data": {"name": bundle.title}, "unit_amount": unit_amount}, "quantity": 1}]
        )
        return jsonify({"sessionId": checkout_session.id})
    except stripe.error.StripeError as e:
        print(f"DEBUG: Stripe checkout error: {e}")
        return jsonify(error="Could not create Stripe checkout session"), 500


@checkout_bp.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    # stripe webhook endpoint
    if not config.STRIPE_WEBHOOK_SECRET:
        print("DEBUG: STRIPE_WEBHOOK_SECRET is missing")
        return jsonify(error="Stripe webhook is not configured"), 500

    payload = request.get_data()
    signature = request.headers.get("Stripe-Signature")

    if not signature:
        return jsonify(error="Missing Stripe signature"), 400

    try:
        event = stripe.Webhook.construct_event(
            payload,
            signature,
            config.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        return jsonify(error="Invalid payload"), 400
    except stripe.error.SignatureVerificationError:
        return jsonify(error="Invalid Stripe signature"), 400

    try:
        if event["type"] == "checkout.session.completed":
            checkout_session = event["data"]["object"]
            meta = _extract_metadata(checkout_session)
            session_id = getattr(checkout_session, "id", None) or (checkout_session.get("id") if isinstance(checkout_session, dict) else None)
            if meta.get("purchase_type") == "gift":
                fulfill_gift(session_id)
            elif meta.get("purchase_type") == "tip":
                fulfill_tip(session_id)
            else:
                fulfill_checkout(session_id)

        elif event["type"] == "checkout.session.async_payment_succeeded":
            checkout_session = event["data"]["object"]
            meta = _extract_metadata(checkout_session)
            session_id = getattr(checkout_session, "id", None) or (checkout_session.get("id") if isinstance(checkout_session, dict) else None)
            if meta.get("purchase_type") == "gift":
                fulfill_gift(session_id)
            elif meta.get("purchase_type") == "tip":
                fulfill_tip(session_id)
            else:
                fulfill_checkout(session_id)

        elif event["type"] == "checkout.session.async_payment_failed":
            checkout_session = event["data"]["object"]
            session_id = getattr(checkout_session, "id", None) or (checkout_session.get("id") if isinstance(checkout_session, dict) else None)
            print(f"DEBUG: Async Stripe payment failed: {session_id}")

        elif event["type"] == "refund.created":
            refund = event["data"]["object"]
            refund_id = getattr(refund, "id", None) or (refund.get("id") if isinstance(refund, dict) else None)
            refund_status = getattr(refund, "status", None) or (refund.get("status") if isinstance(refund, dict) else None)
            purchase = Purchase.query.filter_by(
                stripe_refund_id=refund_id
            ).first()

            if purchase and refund_status in {"succeeded", "pending"}:
                purchase.refunded = True
                purchase.refunded_at = datetime.now(timezone.utc)
                db.session.commit()

        elif event["type"] == "account.updated":
            account = event["data"]["object"]
            acct_id = getattr(account, "id", None) or (account.get("id") if isinstance(account, dict) else None)
            if acct_id:
                user = User.query.filter_by(stripe_connect_id=acct_id).first()
                if user:
                    was_enabled = bool(user.stripe_connect_payouts_enabled)
                    user.stripe_connect_payouts_enabled = bool(getattr(account, "payouts_enabled", False) or (account.get("payouts_enabled", False) if isinstance(account, dict) else False))
                    user.stripe_connect_details_submitted = bool(getattr(account, "details_submitted", False) or (account.get("details_submitted", False) if isinstance(account, dict) else False))
                    user.stripe_connect_charges_enabled = bool(getattr(account, "charges_enabled", False) or (account.get("charges_enabled", False) if isinstance(account, dict) else False))
                    db.session.commit()
                    if not was_enabled and user.stripe_connect_payouts_enabled:
                        process_pending_payouts_for_developer(user)

    except Exception as e:
        # Return 500 so Stripe can retry the webhook when something failed. It shouldn't happen though.
        print(f"DEBUG: Stripe webhook processing error: {e}")
        return jsonify(error="Webhook processing failed"), 500

    return jsonify({"received": True}), 200


@checkout_bp.route("/success/<int:game_id>")
@login_required
def success(game_id):
    game = Game.query.get_or_404(game_id)

    session_id = request.args.get("session_id")

    if not session_id:
        flash("Missing Stripe checkout session.", "error")
        return redirect(url_for("game_detail", game_id=game.id))

    try:
        stripe.api_key = config.stripe_keys["secret_key"]

        checkout_session = stripe.checkout.Session.retrieve(session_id)

        # Secruitycheck
        if checkout_session.client_reference_id != str(current_user.id):
            flash("This payment session does not belong to your account.", "error")
            return redirect(url_for("game_detail", game_id=game.id))

        # Only fulfill purchase on paid session.
        if checkout_session.payment_status != "paid":
            flash("Payment has not been completed yet.", "error")
            return redirect(url_for("game_detail", game_id=game.id))

        # Fallback for local dev
        # we don't want double purchases
        existing_purchase = Purchase.query.filter_by(user_id=current_user.id, game_id=game.id).first()
        if existing_purchase and not existing_purchase.refunded:
            flash("You already own this game.", "error")
        fulfilled = fulfill_checkout(checkout_session.id)

        if fulfilled:
            flash("Purchase successful! The game has been added to your library.", "success")
        else:
            flash(
                "Payment was successful, but the purchase could not be added yet.",
                "error"
            )

    except stripe.error.StripeError as e:
        print(f"DEBUG: Could not verify success session: {e}")
        flash("The payment could not be verified.", "error")

    except Exception as e:
        print(f"DEBUG: Error fulfilling checkout: {e}")
        flash("Something went wrong while adding the game to your library.", "error")

    return render_template("success.html", game=game)


@checkout_bp.route("/bundle_success/<int:bundle_id>")
@login_required
def bundle_success(bundle_id):
    bundle = Bundle.query.get_or_404(bundle_id)
    session_id = request.args.get("session_id")
    if not session_id:
        flash("Missing Stripe checkout session.", "error")
        return redirect(url_for("bundle_detail", bundle_id=bundle.id))

    try:
        stripe.api_key = config.stripe_keys["secret_key"]
        checkout_session = stripe.checkout.Session.retrieve(session_id)

        if checkout_session.client_reference_id != str(current_user.id):
            flash("This payment session does not belong to your account.", "error")
            return redirect(url_for("bundle_detail", bundle_id=bundle.id))

        fulfilled = fulfill_checkout(checkout_session.id)
        if fulfilled:
            flash(f"Purchase successful! All games from '{bundle.title}' are now in your library.", "success")
        else:
            flash("Payment was successful, but the games could not be added yet.", "error")
    except Exception as e:
        flash("Something went wrong.", "error")

    return redirect(url_for("library"))


@checkout_bp.route("/refund/<int:game_id>", methods=["POST"])
@login_required
def refund_purchase(game_id):
    # Request a full Stripe refund and revoke the game's library access.
    purchase = Purchase.query.filter_by(user_id=current_user.id, game_id=game_id, refunded=False).first()
    if not purchase or not purchase.stripe_payment_intent_id:
        flash("Purchase not found or cannot be refunded.", "error")
        return redirect(url_for("library"))

    stripe.api_key = config.stripe_keys["secret_key"]

    # Hole die echte Stripe Payment Intent ID (ohne das '|123' von den Bundles)
    real_pi = purchase.stripe_payment_intent_id.split('|')[0]

    try:
        refund = stripe.Refund.create(
            payment_intent=real_pi,
            reason="requested_by_customer"
        )
        if refund.status not in {"succeeded", "pending"}:
            flash("Stripe did not accept the refund.", "error")
            return redirect(url_for("library"))

        # We find all buyed games in the bundle
        #  You cant exploit this hopefully
        all_related_purchases = Purchase.query.filter(Purchase.stripe_payment_intent_id.like(f"{real_pi}%")).all()

        for p in all_related_purchases:
            p.stripe_refund_id = refund.id
            p.refunded = True
            p.refunded_at = datetime.now(timezone.utc)
            update_daily_stats(p.game)

        db.session.commit()
        if refund.status == "pending":
            flash("Your refund was requested and is currently pending.", "success")
        else:
            flash("Refund successful! The game(s) have been removed from your library.", "success")

    except stripe.error.StripeError as e:
        flash("The refund could not be processed by Stripe.", "error")
    return redirect(url_for("library"))

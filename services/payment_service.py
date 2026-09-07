import json
import stripe
from flask import url_for, has_request_context
from extensions import db
from models.user import User, Notification
from models.game import Game
from models.commerce import Purchase, Gift, Tip
from models.bundle import Bundle
from services.game_service import calculate_display_price, update_daily_stats
from services.mail_service import send_email, _comic_email_shell
from services.badge_service import sync_user_badges
import config


def _extract_metadata(obj):
    if not obj:
        return {}
    meta = getattr(obj, "metadata", None)
    if meta is None and isinstance(obj, dict):
        meta = obj.get("metadata")
    if not meta:
        return {}
    if hasattr(meta, "to_dict"):
        return meta.to_dict()
    if isinstance(meta, dict):
        return meta
    return dict(getattr(meta, "_data", {}))


# ---------------------------------------------------------------------------
# Stripe Connect Helpers & Payout Engine
# ---------------------------------------------------------------------------

def calculate_payout_split(amount, is_tip=False):
    """
    Calculates the automated split between developer earnings and Sqush platform fee.
    Default: 90% Developer, 10% Sqush (0% on tips by default).
    Returns dict: {dev_amount, platform_fee, dev_cents, fee_cents}
    """
    if amount is None or amount <= 0:
        return {
            "dev_amount": 0.0,
            "platform_fee": 0.0,
            "dev_cents": 0,
            "platform_fee_cents": 0,
        }

    fee_percent = config.TIP_PLATFORM_FEE_PERCENT if is_tip else config.PLATFORM_FEE_PERCENT
    total_cents = int(round(amount * 100))
    fee_cents = int(round(total_cents * (fee_percent / 100.0)))
    dev_cents = max(0, total_cents - fee_cents)

    return {
        "dev_amount": round(dev_cents / 100.0, 2),
        "platform_fee": round(fee_cents / 100.0, 2),
        "dev_cents": dev_cents,
        "platform_fee_cents": fee_cents,
    }


def get_or_create_connect_account(user, country="DE"):
    """
    Retrieves or creates a Stripe Connect Express account for the developer.
    """
    if not config.STRIPE_SECRET_KEY:
        raise ValueError("Stripe is not configured")

    stripe.api_key = config.STRIPE_SECRET_KEY

    if user.stripe_connect_id:
        try:
            account = stripe.Account.retrieve(user.stripe_connect_id)
            user.stripe_connect_payouts_enabled = bool(getattr(account, "payouts_enabled", False) or account.get("payouts_enabled", False) if isinstance(account, dict) else False)
            user.stripe_connect_details_submitted = bool(getattr(account, "details_submitted", False) or account.get("details_submitted", False) if isinstance(account, dict) else False)
            user.stripe_connect_charges_enabled = bool(getattr(account, "charges_enabled", False) or account.get("charges_enabled", False) if isinstance(account, dict) else False)
            db.session.commit()
            return account
        except stripe.error.InvalidRequestError:
            # Stale / reset test account ID; recreate it
            user.stripe_connect_id = None
            user.stripe_connect_payouts_enabled = False
            user.stripe_connect_details_submitted = False
            user.stripe_connect_charges_enabled = False
            db.session.commit()

    account = stripe.Account.create(
        type="express",
        country=country,
        email=user.email,
        capabilities={
            "card_payments": {"requested": True},
            "transfers": {"requested": True},
        },
        business_type="individual",
        metadata={
            "user_id": str(user.id),
            "username": user.username,
            "platform": "sqush.io",
        },
    )

    user.stripe_connect_id = account.id
    user.stripe_connect_payouts_enabled = bool(getattr(account, "payouts_enabled", False) or (account.get("payouts_enabled", False) if isinstance(account, dict) else False))
    user.stripe_connect_details_submitted = bool(getattr(account, "details_submitted", False) or (account.get("details_submitted", False) if isinstance(account, dict) else False))
    user.stripe_connect_charges_enabled = bool(getattr(account, "charges_enabled", False) or (account.get("charges_enabled", False) if isinstance(account, dict) else False))
    db.session.commit()
    return account


def create_connect_onboarding_link(user, refresh_url, return_url):
    """
    Creates an account onboarding link directing the developer to Stripe's hosted Express flow.
    """
    account = get_or_create_connect_account(user)
    stripe.api_key = config.STRIPE_SECRET_KEY
    account_link = stripe.AccountLink.create(
        account=account.id,
        refresh_url=refresh_url,
        return_url=return_url,
        type="account_onboarding",
    )
    return account_link.url


def create_connect_login_link(user):
    """
    Creates a single-use login link for the developer to view their Stripe Express Dashboard.
    """
    if not user.stripe_connect_id or not config.STRIPE_SECRET_KEY:
        return None
    stripe.api_key = config.STRIPE_SECRET_KEY
    try:
        login_link = stripe.Account.create_login_link(user.stripe_connect_id)
        return login_link.url
    except Exception as e:
        print(f"DEBUG: create_connect_login_link error: {e}")
        return None


def sync_connect_account_status(user):
    """
    Polls Stripe for the latest account status (e.g. after returning from onboarding).
    """
    if not user.stripe_connect_id or not config.STRIPE_SECRET_KEY:
        return False
    stripe.api_key = config.STRIPE_SECRET_KEY
    try:
        account = stripe.Account.retrieve(user.stripe_connect_id)
        user.stripe_connect_payouts_enabled = bool(getattr(account, "payouts_enabled", False) or (account.get("payouts_enabled", False) if isinstance(account, dict) else False))
        user.stripe_connect_details_submitted = bool(getattr(account, "details_submitted", False) or (account.get("details_submitted", False) if isinstance(account, dict) else False))
        user.stripe_connect_charges_enabled = bool(getattr(account, "charges_enabled", False) or (account.get("charges_enabled", False) if isinstance(account, dict) else False))
        db.session.commit()
        return user.stripe_connect_payouts_enabled
    except Exception as e:
        print(f"DEBUG: sync_connect_account_status error: {e}")
        return False


def transfer_to_developer(user, amount_eur, transfer_group=None, description=None):
    """
    Executes a transfer from the platform balance to a developer's connected Stripe account.
    Used for multi-item cart purchases, bundle splits, and retroactive payouts.
    """
    if not user or not user.stripe_connect_id or not user.stripe_connect_payouts_enabled:
        return None
    if not config.STRIPE_SECRET_KEY or amount_eur <= 0:
        return None

    amount_cents = int(round(amount_eur * 100))
    if amount_cents < 1:
        return None

    stripe.api_key = config.STRIPE_SECRET_KEY
    params = {
        "amount": amount_cents,
        "currency": "eur",
        "destination": user.stripe_connect_id,
        "description": description or f"Sqush Payout for {user.username} ({amount_eur:.2f}€)",
    }
    if transfer_group:
        params["transfer_group"] = str(transfer_group)

    try:
        transfer = stripe.Transfer.create(**params)
        return transfer.id
    except Exception as e:
        print(f"DEBUG: transfer_to_developer failed: {e}")
        return None


def process_pending_payouts_for_developer(user):
    """
    Transfers any previously accumulated purchases or tips marked 'unconnected' or 'pending'
    once the developer finishes Stripe Connect onboarding.
    """
    if not user or not user.stripe_connect_id or not user.stripe_connect_payouts_enabled:
        return 0

    transferred_count = 0

    # 1. Process pending game purchases
    purchases = (
        Purchase.query.join(Game, Purchase.game_id == Game.id)
        .filter(
            Game.developer_id == user.id,
            Purchase.refunded == False,
            Purchase.payout_status.in_(["unconnected", "pending"]),
        )
        .all()
    )
    for p in purchases:
        dev_cut = p.dev_payout_amount
        if dev_cut is None:
            split = calculate_payout_split(p.price_paid)
            dev_cut = split["dev_amount"]
            p.dev_payout_amount = dev_cut
            p.platform_fee_amount = split["platform_fee"]

        if dev_cut > 0:
            tr_id = transfer_to_developer(
                user,
                dev_cut,
                transfer_group=p.stripe_checkout_session_id,
                description=f"Retroactive payout: {p.game.title} (Purchase #{p.id})",
            )
            if tr_id:
                p.stripe_transfer_id = tr_id
                p.payout_status = "transferred"
                transferred_count += 1
        else:
            p.payout_status = "direct"

    # 2. Process pending tips
    tips = Tip.query.filter(
        Tip.developer_id == user.id,
        Tip.payout_status.in_(["unconnected", "pending"]),
    ).all()
    for t in tips:
        dev_cut = t.dev_payout_amount
        if dev_cut is None:
            split = calculate_payout_split(t.amount, is_tip=True)
            dev_cut = split["dev_amount"]
            t.dev_payout_amount = dev_cut
            t.platform_fee_amount = split["platform_fee"]

        if dev_cut > 0:
            tr_id = transfer_to_developer(
                user,
                dev_cut,
                transfer_group=t.stripe_checkout_session_id,
                description=f"Retroactive tip payout: {t.game.title} (Tip #{t.id})",
            )
            if tr_id:
                t.stripe_transfer_id = tr_id
                t.payout_status = "transferred"
                transferred_count += 1
        else:
            t.payout_status = "direct"

    db.session.commit()
    return transferred_count


# ---------------------------------------------------------------------------
# Fulfillment Functions with Automated Revenue Splitting
# ---------------------------------------------------------------------------

def fulfill_checkout(checkout_session_id):
    # Create the local Purchase only after Stripe confirms payment.
    stripe.api_key = config.stripe_keys["secret_key"]
    checkout_session = stripe.checkout.Session.retrieve(checkout_session_id)
    if checkout_session.payment_status != "paid":
        return False
    metadata = _extract_metadata(checkout_session)

    try:
        user_id = int(metadata["user_id"])
    except (KeyError, TypeError, ValueError):
        return False

    user = db.session.get(User, user_id)
    if not user:
        return False

    is_direct_destination = (metadata.get("is_destination_charge") == "true")

    # When bundle
    if "bundle_id" in metadata:
        bundle = db.session.get(Bundle, int(metadata["bundle_id"]))
        if not bundle:
            return False

        price_per_game = bundle.display_price / len(bundle.games) if bundle.games else 0

        for bg in bundle.games:
            game = bg.game
            unique_session_id = f"{checkout_session.id}|{game.id}"

            existing = Purchase.query.filter_by(stripe_checkout_session_id=unique_session_id).first()
            if not existing:
                split = calculate_payout_split(price_per_game)
                dev_user = game.user
                tr_id = None
                p_status = "unconnected"

                if dev_user and dev_user.stripe_connect_id and dev_user.stripe_connect_payouts_enabled and split["dev_amount"] > 0:
                    tr_id = transfer_to_developer(
                        dev_user,
                        split["dev_amount"],
                        transfer_group=checkout_session.id,
                        description=f"Bundle sale: {bundle.title} ({game.title})",
                    )
                    p_status = "transferred" if tr_id else "pending"

                p = Purchase(
                    user_id=user.id,
                    game_id=game.id,
                    price_paid=price_per_game,
                    stripe_checkout_session_id=unique_session_id,
                    stripe_payment_intent_id=f"{checkout_session.payment_intent}|{game.id}",
                    refunded=False,
                    dev_payout_amount=split["dev_amount"],
                    platform_fee_amount=split["platform_fee"],
                    stripe_transfer_id=tr_id,
                    payout_status=p_status,
                )
                db.session.add(p)
                update_daily_stats(game)
        db.session.commit()
        sync_user_badges(user)
        return True

    # When its a single game
    elif "game_id" in metadata:
        game_id = int(metadata["game_id"])

        existing_purchase = Purchase.query.filter_by(stripe_checkout_session_id=checkout_session.id).first()
        if existing_purchase:
            return True

        game = db.session.get(Game, game_id)
        if not game:
            return False

        price_paid = calculate_display_price(game)
        split = calculate_payout_split(price_paid)
        dev_user = game.user

        tr_id = None
        if is_direct_destination:
            p_status = "direct"
        elif dev_user and dev_user.stripe_connect_id and dev_user.stripe_connect_payouts_enabled and split["dev_amount"] > 0:
            tr_id = transfer_to_developer(
                dev_user,
                split["dev_amount"],
                transfer_group=checkout_session.id,
                description=f"Game sale: {game.title}",
            )
            p_status = "transferred" if tr_id else "pending"
        else:
            p_status = "unconnected"

        existing_purchase = Purchase.query.filter_by(user_id=user.id, game_id=game_id).first()
        if existing_purchase and not existing_purchase.refunded:
            if not existing_purchase.stripe_checkout_session_id:
                existing_purchase.stripe_checkout_session_id = checkout_session.id
            if not existing_purchase.stripe_payment_intent_id:
                existing_purchase.stripe_payment_intent_id = checkout_session.payment_intent
            if existing_purchase.dev_payout_amount is None:
                existing_purchase.dev_payout_amount = split["dev_amount"]
                existing_purchase.platform_fee_amount = split["platform_fee"]
                existing_purchase.stripe_transfer_id = tr_id
                existing_purchase.payout_status = p_status
            db.session.commit()
            sync_user_badges(user)
            return True

        purchase = Purchase(
            user_id=user.id,
            game_id=game_id,
            price_paid=price_paid,
            stripe_checkout_session_id=checkout_session.id,
            stripe_payment_intent_id=checkout_session.payment_intent,
            refunded=False,
            dev_payout_amount=split["dev_amount"],
            platform_fee_amount=split["platform_fee"],
            stripe_transfer_id=tr_id,
            payout_status=p_status,
        )
        db.session.add(purchase)
        db.session.commit()
        update_daily_stats(game)
        sync_user_badges(user)
        return True

    # When its a cart (multiple individual games in one session)
    elif "cart_game_ids" in metadata:
        try:
            cart_ids = json.loads(metadata["cart_game_ids"])
        except (ValueError, TypeError):
            return False

        for game_id in cart_ids:
            game = db.session.get(Game, int(game_id))
            if not game:
                continue
            unique_session_id = f"{checkout_session.id}|{game.id}"
            existing = Purchase.query.filter_by(stripe_checkout_session_id=unique_session_id).first()
            if not existing:
                price_paid = calculate_display_price(game)
                split = calculate_payout_split(price_paid)
                dev_user = game.user
                tr_id = None
                p_status = "unconnected"

                if dev_user and dev_user.stripe_connect_id and dev_user.stripe_connect_payouts_enabled and split["dev_amount"] > 0:
                    tr_id = transfer_to_developer(
                        dev_user,
                        split["dev_amount"],
                        transfer_group=checkout_session.id,
                        description=f"Cart sale: {game.title}",
                    )
                    p_status = "transferred" if tr_id else "pending"

                p = Purchase(
                    user_id=user.id,
                    game_id=game.id,
                    price_paid=price_paid,
                    stripe_checkout_session_id=unique_session_id,
                    stripe_payment_intent_id=f"{checkout_session.payment_intent}|{game.id}",
                    refunded=False,
                    dev_payout_amount=split["dev_amount"],
                    platform_fee_amount=split["platform_fee"],
                    stripe_transfer_id=tr_id,
                    payout_status=p_status,
                )
                db.session.add(p)
                update_daily_stats(game)
        db.session.commit()
        sync_user_badges(user)
        return True

    return False


def fulfill_gift(checkout_session_id):
    # that thing is called by the stripe webhook after a succesfull payment.
    # It creates the purchase on the Recipients account and stores a gift row (so we know THAT I SEND IT) and it sends the recipient an email
    # fully independent here
    stripe.api_key = config.stripe_keys["secret_key"]
    cs = stripe.checkout.Session.retrieve(checkout_session_id)
    if cs.payment_status != "paid":
        return False

    metadata = _extract_metadata(cs)
    if metadata.get("purchase_type") != "gift":
        return False

    try:
        sender_id = int(metadata["user_id"])
        recipient_id = int(metadata["recipient_id"])
        game_id = int(metadata["game_id"])
    except (KeyError, TypeError, ValueError):
        return False

    gift_message = metadata.get("gift_message", "")

    # Idempotency guard: Gift row already exists for this session?
    existing_gift = Gift.query.filter_by(
        stripe_checkout_session_id=checkout_session_id
    ).first()
    if existing_gift:
        return True

    game = db.session.get(Game, game_id)
    if not game:
        return False

    # Book the purchase on the RECIPIENT (not the sender who paid)
    price_paid = calculate_display_price(game)
    split = calculate_payout_split(price_paid)
    dev_user = game.user
    is_direct_destination = (metadata.get("is_destination_charge") == "true")
    tr_id = None

    if is_direct_destination:
        p_status = "direct"
    elif dev_user and dev_user.stripe_connect_id and dev_user.stripe_connect_payouts_enabled and split["dev_amount"] > 0:
        tr_id = transfer_to_developer(
            dev_user,
            split["dev_amount"],
            transfer_group=cs.id,
            description=f"Gift sale: {game.title}",
        )
        p_status = "transferred" if tr_id else "pending"
    else:
        p_status = "unconnected"

    existing_purchase = Purchase.query.filter_by(
        user_id=recipient_id, game_id=game_id, refunded=False
    ).first()
    if not existing_purchase:
        p = Purchase(
            user_id=recipient_id,
            game_id=game_id,
            price_paid=price_paid,
            stripe_checkout_session_id=checkout_session_id,
            stripe_payment_intent_id=cs.payment_intent,
            refunded=False,
            dev_payout_amount=split["dev_amount"],
            platform_fee_amount=split["platform_fee"],
            stripe_transfer_id=tr_id,
            payout_status=p_status,
        )
        db.session.add(p)
        update_daily_stats(game)

    # Create the Gift record so we always know who the sender was
    gift = Gift(
        sender_id=sender_id,
        recipient_id=recipient_id,
        game_id=game_id,
        stripe_checkout_session_id=checkout_session_id,
        stripe_payment_intent_id=cs.payment_intent,
        message=gift_message,
    )
    db.session.add(gift)

    # Notify the recipient
    sender = db.session.get(User, sender_id)
    sender_name = sender.username if sender else "Someone"
    notif_msg = f"{sender_name} gifted you '{game.title}'!"
    if gift_message:
        notif_msg += f' "{gift_message[:100]}"'
    db.session.add(Notification(
        user_id=recipient_id,
        message=notif_msg,
        type="gift_received",
    ))

    recipient = db.session.get(User, recipient_id)
    if recipient and recipient.email:
        try:
            lib_url = url_for("library", _external=True) if has_request_context() else "/library"
        except Exception:
            lib_url = "/library"

        email_body = f"""
          <p>Hey {recipient.username},</p>
          <p><strong>{sender_name}</strong> just gifted you <strong>{game.title}</strong> on Sqush!</p>
          {f'<p style="background:#222;padding:12px;border-left:4px solid #ffe14d;color:#eee;">"{gift_message}"</p>' if gift_message else ''}
          <p style="text-align:center;margin:28px 0;">
            <a href="{lib_url}"
               style="background:#33d17a;color:#000;font-weight:bold;text-decoration:none;
                      padding:12px 24px;border:3px solid #000;display:inline-block;">
              GO TO YOUR LIBRARY
            </a>
          </p>
        """
        send_email(recipient.email, f"{sender_name} gifted you {game.title}!", _comic_email_shell("You received a gift!", email_body))

    db.session.commit()
    if sender:
        sync_user_badges(sender)
    if recipient:
        sync_user_badges(recipient)
    return True


def fulfill_tip(checkout_session_id):
    # called after stripe confirms the tip. Dev gets the cash, tipper gets love (:
    stripe.api_key = config.stripe_keys["secret_key"]
    cs = stripe.checkout.Session.retrieve(checkout_session_id)
    if cs.payment_status != "paid":
        return False

    metadata = _extract_metadata(cs)
    if metadata.get("purchase_type") != "tip":
        return False

    #  Tip row already exists?
    existing_tip = Tip.query.filter_by(
        stripe_checkout_session_id=checkout_session_id
    ).first()
    if existing_tip:
        return True

    try:
        developer_id = int(metadata["developer_id"])
        game_id = int(metadata["game_id"])
        amount = float(metadata.get("tip_amount", 0))
    except (KeyError, TypeError, ValueError):
        return False

    user_id_raw = metadata.get("user_id")
    user_id = int(user_id_raw) if user_id_raw and user_id_raw.isdigit() else None
    tip_message = metadata.get("tip_message", "")
    supporter_name = metadata.get("supporter_name", "").strip() or "Anonymous Fan"

    game = db.session.get(Game, game_id)
    developer = db.session.get(User, developer_id)
    if not game or not developer:
        return False

    tipper = db.session.get(User, user_id) if user_id else None
    if tipper:
        supporter_name = tipper.username

    split = calculate_payout_split(amount, is_tip=True)
    is_direct_destination = (metadata.get("is_destination_charge") == "true")
    tr_id = None

    if is_direct_destination:
        p_status = "direct"
    elif developer.stripe_connect_id and developer.stripe_connect_payouts_enabled and split["dev_amount"] > 0:
        tr_id = transfer_to_developer(
            developer,
            split["dev_amount"],
            transfer_group=cs.id,
            description=f"Tip for {game.title}",
        )
        p_status = "transferred" if tr_id else "pending"
    else:
        p_status = "unconnected"

    tip = Tip(
        user_id=user_id,
        developer_id=developer_id,
        game_id=game_id,
        amount=amount,
        message=tip_message,
        supporter_name=supporter_name,
        stripe_checkout_session_id=checkout_session_id,
        stripe_payment_intent_id=cs.payment_intent,
        dev_payout_amount=split["dev_amount"],
        platform_fee_amount=split["platform_fee"],
        stripe_transfer_id=tr_id,
        payout_status=p_status,
    )
    db.session.add(tip)

    # in app notification for developer
    notif_msg = f"{supporter_name} sent you a {amount:.2f}€ tip for '{game.title}'!"
    if tip_message:
        notif_msg += f' "{tip_message[:100]}"'
    db.session.add(Notification(
        user_id=developer_id,
        message=notif_msg,
        type="tip_received",
    ))

    # send email to the dev so they know they got cash (:
    if developer.email:
        try:
            game_url = url_for("main.game_detail", game_id=game.id, _external=True) if has_request_context() else f"/game/{game.id}"
        except Exception:
            game_url = f"/game/{game.id}"

        email_body = f"""
          <p>Hey {developer.username},</p>
          <p>Great news! <strong>{supporter_name}</strong> dropped a <strong>{amount:.2f}€</strong> tip into your Tip Jar for <strong>{game.title}</strong>!</p>
          {f'<p style="background:#222;padding:12px;border-left:4px solid #ffe14d;color:#eee;">"{tip_message}"</p>' if tip_message else ''}
          <p style="text-align:center;margin:28px 0;">
            <a href="{game_url}"
               style="background:#33d17a;color:#000;font-weight:bold;text-decoration:none;
                      padding:12px 24px;border:3px solid #000;display:inline-block;">
              VIEW GAME
            </a>
          </p>
        """
        send_email(
            developer.email,
            f"New tip: {amount:.2f}€ from {supporter_name} for {game.title} (:",
            _comic_email_shell("New tip in your Tip Jar!", email_body)
        )

    db.session.commit()

    if tipper:
        sync_user_badges(tipper)

    return True


import json
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import current_user, login_required
import stripe
from extensions import db
from models.user import User, Notification
from models.game import Game, GameUpdate, Screenshot, Video, GameStats
from models.commerce import Purchase, Wishlist, Tip
from models.bundle import Bundle, BundleGame, BundleCollaborator
from services.auth_service import bundle_role
from services.file_service import allowed_file, save_file, save_game_file
from services.game_service import (
    calculate_display_price,
    calculate_game_revenue,
    calculate_game_tips,
    update_daily_stats,
)
from services.payment_service import (
    calculate_payout_split,
    create_connect_onboarding_link,
    create_connect_login_link,
    sync_connect_account_status,
    process_pending_payouts_for_developer,
)
import config

developer_bp = Blueprint("developer", __name__)


# bundle dashboard stuff (:
@developer_bp.route("/dashboard/bundles")
@login_required
def developer_bundles():
    if current_user.role != "dev":
        return "Access Denied", 403

    owned = Bundle.query.filter_by(owner_id=current_user.id).all()

    invited = BundleCollaborator.query.filter_by(
        user_id=current_user.id,
        status="pending"
    ).all()

    collabs = [
        x.bundle
        for x in BundleCollaborator.query.filter_by(
            user_id=current_user.id,
            status="accepted"
        ).all()
    ]

    return render_template(
        "bundles.html",
        owned_bundles=owned,
        pending_invites=invited,
        collaborating_bundles=collabs
    )


@developer_bp.route("/dashboard/bundles/create", methods=["POST"])
@login_required
def create_bundle():
    if current_user.role != "dev":
        return "Access Denied", 403

    title = request.form.get("title", "").strip()
    discount = request.form.get("discount_percent", type=int)

    if not title or discount is None or not 0 <= discount <= 95:
        flash("Please check title and discount (0-95%).", "error")
        return redirect(url_for("developer_bundles"))

    image = request.files.get("image")

    if image and image.filename and not allowed_file(image.filename):
        flash("Only image files are allowed.", "error")
        return redirect(url_for("developer_bundles"))

    b = Bundle(
        title=title,
        description=request.form.get("description", "").strip() or None,
        discount_percent=discount,
        owner_id=current_user.id,
        image_path=(
            save_file(image)
            if image and image.filename
            else None
        )
    )

    db.session.add(b)
    db.session.commit()

    return redirect(url_for("edit_bundle", bundle_id=b.id))


@developer_bp.route("/dashboard/bundle/<int:bundle_id>")
@login_required
def edit_bundle(bundle_id):
    bundle = Bundle.query.get_or_404(bundle_id)
    role = bundle_role(bundle, current_user)

    if not role:
        return "Access Denied", 403

    my_games = Game.query.filter_by(
        developer_id=current_user.id
    ).all()

    return render_template(
        "edit_bundle.html",
        bundle=bundle,
        role=role,
        my_games=my_games
    )


@developer_bp.route("/dashboard/bundle/<int:bundle_id>/games", methods=["POST"])
@login_required
def add_game_to_bundle(bundle_id):
    bundle = Bundle.query.get_or_404(bundle_id)

    if bundle_role(bundle, current_user) not in (
            "owner",
            "manager",
            "contributor"
    ):
        return "Access Denied", 403

    game = db.session.get(
        Game,
        request.form.get("game_id", type=int)
    )

    if not game or game.developer_id != current_user.id:
        flash(
            "You can only add your own games.",
            "error"
        )
    elif BundleGame.query.filter_by(
            bundle_id=bundle.id,
            game_id=game.id
    ).first():
        flash("Game is already in this bundle.", "info")
    else:
        db.session.add(
            BundleGame(
                bundle_id=bundle.id,
                game_id=game.id
            )
        )
        db.session.commit()
        flash("Game added.", "success")

    return redirect(
        url_for("edit_bundle", bundle_id=bundle.id)
    )


@developer_bp.route("/dashboard/bundle/<int:bundle_id>/invite", methods=["POST"])
@login_required
def invite_bundle_collaborator(bundle_id):
    bundle = Bundle.query.get_or_404(bundle_id)

    if bundle_role(bundle, current_user) not in (
            "owner",
            "manager"
    ):
        return "Access Denied", 403

    target = User.query.filter_by(
        username=request.form.get("username", "").strip()
    ).first()

    role = request.form.get("role", "contributor")

    if role not in ("manager", "contributor"):
        role = "contributor"

    if (
            not target
            or target.role != "dev"
            or target.id == bundle.owner_id
    ):
        flash("Developer not found.", "error")
        return redirect(
            url_for("edit_bundle", bundle_id=bundle.id)
        )

    if BundleCollaborator.query.filter_by(
            bundle_id=bundle.id,
            user_id=target.id
    ).first():
        flash("Developer has already been invited.", "info")
        return redirect(
            url_for("edit_bundle", bundle_id=bundle.id)
        )

    invite = BundleCollaborator(
        bundle_id=bundle.id,
        user_id=target.id,
        invited_by_id=current_user.id,
        role=role
    )

    db.session.add(invite)

    db.session.add(
        Notification(
            user_id=target.id,
            message=(
                f"{current_user.username} invited you to collaborate "
                f"on '{bundle.title}'."
            ),
            type="bundle_invite"
        )
    )

    db.session.commit()

    flash("Invitation sent.", "success")

    return redirect(
        url_for("edit_bundle", bundle_id=bundle.id)
    )


@developer_bp.route("/dashboard/bundle/invitation/<int:invite_id>")
@login_required
def bundle_invitation_detail(invite_id):
    invite = BundleCollaborator.query.get_or_404(invite_id)

    if invite.user_id != current_user.id:
        return "Access Denied", 403

    return render_template(
        "bundle_invitation.html",
        invite=invite
    )


@developer_bp.route(
    "/dashboard/bundle/invitation/<int:invite_id>/<action>",
    methods=["POST"]
)
@login_required
def respond_to_bundle_invite(invite_id, action):
    invite = BundleCollaborator.query.get_or_404(invite_id)

    if (
            invite.user_id != current_user.id
            or invite.status != "pending"
    ):
        return "Access Denied", 403

    if action not in ("accept", "decline"):
        return "Invalid action", 400

    invite.status = (
        "accepted"
        if action == "accept"
        else "declined"
    )

    db.session.add(
        Notification(
            user_id=invite.invited_by_id,
            message=(
                f"{current_user.username} {action}ed your invite "
                f"for '{invite.bundle.title}'."
            ),
            type="bundle_invite_response"
        )
    )

    db.session.commit()

    return redirect(url_for("developer_bundles"))


@developer_bp.route("/dashboard/bundle/<int:bundle_id>/publish", methods=["POST"])
@login_required
def publish_bundle(bundle_id):
    # just for the devs
    bundle = Bundle.query.get_or_404(bundle_id)
    if bundle_role(bundle, current_user) != "owner":
        return "Access Denied", 403
    bundle.is_published = not bundle.is_published
    db.session.commit()
    flash(f"Bundle is now {'published' if bundle.is_published else 'hidden'}.", "success")
    return redirect(url_for('edit_bundle', bundle_id=bundle.id))


@developer_bp.route("/edit_game/<int:game_id>", methods=["GET", "POST"])
@login_required
def edit_game(game_id):
    #yea for some reason anonymus visitors could just edit any game.
    #should be fixed now.
    game = Game.query.get_or_404(game_id)
    if current_user.role != "dev":
        return "Access Denied. How could you?", 403
    if game.developer_id != current_user.id:
        return "Access Denied: Better Luck next time (:", 403

    if request.method == "POST":
        game.title = request.form["title"]
        game.price = float(request.form["price"])
        game.description = request.form.get("description")
        game.is_on_sale = "is_on_sale" in request.form
        game.discount_percent = int(request.form.get("discount_percent", 0))

        # only overwrites the demo if it actually passes the secruity check
        demo_file = request.files.get("demo_file")
        if demo_file and demo_file.filename:
            new_demo_path, demo_error = save_game_file(demo_file)
            if demo_error:
                flash(f"Demo file rejected: {demo_error}", "error")
                return redirect(url_for("edit_game", game_id=game.id))
            game.demo_path = new_demo_path

        files = request.files.getlist("screenshots")
        for f in files:
            if f and f.filename:
                path = save_file(f)
                db.session.add(Screenshot(game_id=game.id, image_path=path))

        video_files = request.files.getlist("videos")
        for v in video_files:
            path = save_file(v)
            if path:
                db.session.add(Video(game_id=game.id, video_path=path))

        db.session.commit()
        return redirect(url_for("developer_dashboard"))
    return render_template("edit_game.html", game=game)


@developer_bp.route("/dashboard/game/<int:game_id>/update", methods=["GET", "POST"])
@login_required
def update_game(game_id):
    #I will add vlogs tommorow so its already a table there.
    game = Game.query.get_or_404(game_id)
    if current_user.role != "dev":
        return "Access Denied. How could you?", 403
    if game.developer_id != current_user.id:
        return "Access Denied: Better Luck next time (:", 403

    if request.method == "POST":
        version_label = request.form.get("version_label", "").strip() or None
        patch_notes = request.form.get("patch_notes", "").strip() or None
        new_file = request.files.get("game_file")

        if not new_file or not new_file.filename:
            flash("Pick a file for the update", "error")
            return redirect(url_for("update_game", game_id=game.id))

        new_path, error = save_game_file(new_file)
        if error:
            flash(f"Update rejected: {error}", "error")
            return redirect(url_for("update_game", game_id=game.id))

        game.download_path = new_path
        update_entry = GameUpdate(
            game_id=game.id,
            file_path=new_path,
            version_label=version_label,
            patch_notes=patch_notes
        )
        db.session.add(update_entry)
        db.session.commit()

        # tell everyone who follows this game that a fresh update just dropped
        followers = GameFollow.query.filter_by(game_id=game.id).all()
        for f in followers:
            if f.user_id != current_user.id:
                db.session.add(Notification(
                    user_id=f.user_id,
                    message=f"{game.title} got a new update"
                            + (f" ({version_label})" if version_label else "")
                            + "!",
                    type="game_update"
                ))
        db.session.commit()

        flash("Game updated! The new build is live.", "success")
        return redirect(url_for("developer_dashboard"))

    history = GameUpdate.query.filter_by(game_id=game.id).order_by(GameUpdate.created_at.desc()).all()
    return render_template("update_game.html", game=game, history=history)


#It's a dev panel now ):
@developer_bp.route("/dashboard", methods=["GET", "POST"])
@login_required
def developer_dashboard():
    if current_user.role != "dev":
        return "Access Denied: Better Luck next time (:", 403

    if request.method == "POST":
        #merged the block together
        sale_end_date = None
        sale_end_date_str = request.form.get("sale_end_date")
        if sale_end_date_str:
            try:
                sale_end_date = datetime.strptime(sale_end_date_str, "%Y-%m-%dT%H:%M")
            except ValueError:
                sale_end_date = None

        title = request.form["title"]
        genre = request.form["genre"]
        priority = request.form.get("priority", "normal")
        tags = request.form["tags"]
        price = float(request.form["price"])
        description = request.form.get("description")
        is_on_sale = "is_on_sale" in request.form
        discount_percent = int(request.form.get("discount_percent", 0))

        image_file = request.files.get("image")
        uploaded_video = request.files.get("video_file")
        video_youtube = request.form.get("video_youtube", "").strip()
        game_file = request.files.get("game_file")
        demo_file = request.files.get("demo_file")

        image_path = save_file(image_file) if image_file else ""

        if uploaded_video and uploaded_video.filename:
            video_path = save_file(uploaded_video)
        elif video_youtube:
            if "v=" in video_youtube:
                yt_id = video_youtube.split("v=")[1].split("&")[0]
            elif "youtu.be/" in video_youtube:
                yt_id = video_youtube.split("youtu.be/")[1].split("?")[0]
            else:
                yt_id = video_youtube
            video_path = f"youtube:{yt_id}"
        else:
            video_path = "https://www.youtube.com/watch?v=E4WlUXrJgy4"

        #well all of this is getting scanned. (For secruity reasons of course(: )
        download_path, game_file_error = save_game_file(game_file)
        if game_file_error:
            flash(f"Game file rejected: {game_file_error}", "error")
            return redirect(url_for("developer_dashboard"))
        if not download_path:
            flash("You need to upload a game file", "error")
            return redirect(url_for("developer_dashboard"))

        demo_path, demo_file_error = save_game_file(demo_file)
        if demo_file_error:
            flash(f"Demo file rejected: {demo_file_error}", "error")
            return redirect(url_for("developer_dashboard"))

        new_game = Game(title=title, genre=genre, priority=priority, tags=tags, price=price,
                        image_path=image_path, video_path=video_path, description=description,
                        download_path=download_path, demo_path=demo_path, is_on_sale=is_on_sale, sale_end_date=sale_end_date,
                        discount_percent=discount_percent, developer_id=current_user.id)

        db.session.add(new_game)
        db.session.commit()

        files = request.files.getlist("screenshots")
        for f in files:
            path = save_file(f)
            if path:
                db.session.add(Screenshot(game_id=new_game.id, image_path=path))

        db.session.commit()
        return redirect(url_for("store_front"))

    my_games = Game.query.filter_by(developer_id=current_user.id).all()
    for game in my_games:
        game.display_price = calculate_display_price(game)
        game.total_tips = calculate_game_tips(game)
    return render_template("admin.html", games=my_games)


@developer_bp.route("/dashboard/game/<int:game_id>/stats")
@login_required
def game_stats(game_id):
    game = Game.query.get_or_404(game_id)
    if current_user.role != "dev":
        return "Access Denied. How could you?", 403
    if game.developer_id != current_user.id:
        return "Access Denied: Better Luck next time (:", 403

    # make sure today's data point is up to date before we show it
    update_daily_stats(game)

    history = GameStats.query.filter_by(game_id=game.id).order_by(GameStats.date.asc()).all()

    chart_data = {
        "labels": [h.date.strftime("%d.%m.%Y") for h in history],
        "views": [h.views for h in history],
        "wishlists": [h.wishlist_count for h in history],
        "purchases": [h.purchase_count for h in history],
        "revenue": [h.revenue for h in history]
    }

    current_wishlist_count = Wishlist.query.filter_by(game_id=game.id).count()
    current_purchase_count = Purchase.query.filter_by(game_id=game.id).count()
    total_tips = calculate_game_tips(game)

    return render_template(
        "game_stats.html",
        game=game,
        chart_json=json.dumps(chart_data),
        current_wishlist_count=current_wishlist_count,
        current_purchase_count=current_purchase_count,
        total_revenue=calculate_game_revenue(game),
        total_tips=total_tips,
        tips=game.tips,
    )


@developer_bp.route("/dashboard/revenue")
@login_required
def developer_revenue():
    if current_user.role != "dev":
        return "Access Denied. How could you?", 403

    # ask stripe if this dev is ready for payouts yet (:
    if current_user.stripe_connect_id and config.STRIPE_SECRET_KEY:
        try:
            sync_connect_account_status(current_user)
        except Exception:
            pass

    my_games = Game.query.filter_by(developer_id=current_user.id).all()
    my_game_ids = [g.id for g in my_games]

    revenue_data = []
    total_revenue = 0
    total_tips = 0
    total_dev_payouts = 0.0
    total_platform_fees = 0.0
    pending_payout_amount = 0.0

    for game in my_games:
        game_revenue = calculate_game_revenue(game)
        game_tips = calculate_game_tips(game)
        total_revenue += game_revenue
        total_tips += game_tips
        sales_count = Purchase.query.filter_by(game_id=game.id, refunded=False).count()
        tips_count = Tip.query.filter_by(game_id=game.id).count()

        split = calculate_payout_split(game_revenue)
        game_dev_payout = split["dev_amount"]
        game_fee = split["platform_fee"]

        total_dev_payouts += game_dev_payout
        total_platform_fees += game_fee

        revenue_data.append({
            "game": game,
            "revenue": game_revenue,
            "tips": game_tips,
            "dev_payout": game_dev_payout,
            "platform_fee": game_fee,
            "total_earned": game_dev_payout + game_tips,
            "sales_count": sales_count,
            "tips_count": tips_count,
        })

    # see what people bought recently xD
    recent_purchases = (
        Purchase.query.filter(Purchase.game_id.in_(my_game_ids), Purchase.refunded == False)
        .order_by(Purchase.purchased_at.desc())
        .limit(20)
        .all()
    ) if my_game_ids else []

    transactions = []
    for p in recent_purchases:
        dev_cut = p.dev_payout_amount if p.dev_payout_amount is not None else calculate_payout_split(p.price_paid)["dev_amount"]
        fee_cut = p.platform_fee_amount if p.platform_fee_amount is not None else calculate_payout_split(p.price_paid)["platform_fee"]
        if p.payout_status == "unconnected":
            pending_payout_amount += dev_cut

        transactions.append({
            "type": "sale",
            "date": p.purchased_at,
            "game_title": p.game.title if p.game else "Unknown Game",
            "gross_amount": p.price_paid or 0.0,
            "dev_amount": dev_cut,
            "platform_fee": fee_cut,
            "payout_status": p.payout_status or "pending",
            "stripe_transfer_id": p.stripe_transfer_id,
        })

    # fresh tips for the dev (:
    recent_tips = (
        Tip.query.filter_by(developer_id=current_user.id)
        .order_by(Tip.created_at.desc())
        .limit(10)
        .all()
    )
    for t in recent_tips:
        dev_cut = t.dev_payout_amount if t.dev_payout_amount is not None else calculate_payout_split(t.amount, is_tip=True)["dev_amount"]
        fee_cut = t.platform_fee_amount if t.platform_fee_amount is not None else calculate_payout_split(t.amount, is_tip=True)["platform_fee"]
        if t.payout_status == "unconnected":
            pending_payout_amount += dev_cut

        transactions.append({
            "type": "tip",
            "date": t.created_at,
            "game_title": f"Tip ({t.supporter_name})",
            "gross_amount": t.amount,
            "dev_amount": dev_cut,
            "platform_fee": fee_cut,
            "payout_status": t.payout_status or "pending",
            "stripe_transfer_id": t.stripe_transfer_id,
        })

    # newest money first (:
    transactions.sort(key=lambda x: x["date"] or datetime.min, reverse=True)

    revenue_data.sort(key=lambda x: x["total_earned"], reverse=True)

    return render_template(
        "developer_revenue.html",
        revenue_data=revenue_data,
        total_revenue=total_revenue,
        total_tips=total_tips,
        total_dev_payouts=total_dev_payouts,
        total_platform_fees=total_platform_fees,
        pending_payout_amount=pending_payout_amount,
        transactions=transactions[:25],
        dev_cut_percent=config.DEV_PAYOUT_PERCENT,
        platform_cut_percent=config.PLATFORM_FEE_PERCENT,
        stripe_configured=bool(config.STRIPE_SECRET_KEY),
    )


# getting devs set up with stripe connect so they get paid xD
@developer_bp.route("/dashboard/stripe-connect/connect")
@login_required
def stripe_connect_onboard():
    if current_user.role != "dev":
        return "Access Denied", 403

    if not config.STRIPE_SECRET_KEY:
        flash("Stripe is not configured on this server yet. Add STRIPE_SECRET_KEY to test Connect.", "error")
        return redirect(url_for("developer.developer_revenue"))

    try:
        refresh_url = url_for("developer.stripe_connect_refresh", _external=True)
        return_url = url_for("developer.stripe_connect_return", _external=True)
        onboarding_url = create_connect_onboarding_link(current_user, refresh_url, return_url)
        return redirect(onboarding_url)
    except stripe.error.InvalidRequestError as e:
        err_msg = str(e)
        if "signed up for Connect" in err_msg:
            print("[Stripe Connect] Platform account has not enabled Connect at https://dashboard.stripe.com/connect")
            flash(
                "Stripe Connect has not been enabled on this Stripe account yet! "
                "Please open https://dashboard.stripe.com/connect (in Test Mode) and click 'Get started' to activate Connect. "
                "Once activated, try linking your account again.",
                "error"
            )
        else:
            print(f"[Stripe Connect] InvalidRequestError: {e}")
            flash(f"Could not initialize Stripe Connect: {e}", "error")
        return redirect(url_for("developer.developer_revenue"))
    except Exception as e:
        print(f"DEBUG: Stripe Connect onboarding error: {e}")
        flash(f"Could not initialize Stripe Connect: {e}", "error")
        return redirect(url_for("developer.developer_revenue"))


@developer_bp.route("/dashboard/stripe-connect/return")
@login_required
def stripe_connect_return():
    if current_user.role != "dev":
        return "Access Denied", 403

    try:
        enabled = sync_connect_account_status(current_user)
        if enabled:
            payouts_count = process_pending_payouts_for_developer(current_user)
            msg = "Stripe Connect is connected and payouts are active!"
            if payouts_count > 0:
                msg += f" {payouts_count} previous pending sales were automatically transferred to your account."
            flash(msg, "success")
        else:
            flash("Stripe onboarding received. Finish verification with Stripe to enable automatic payouts.", "info")
    except Exception as e:
        print(f"DEBUG: Stripe Connect return error: {e}")
        flash("An error occurred while verifying your Stripe status.", "error")

    return redirect(url_for("developer.developer_revenue"))


@developer_bp.route("/dashboard/stripe-connect/refresh")
@login_required
def stripe_connect_refresh():
    if current_user.role != "dev":
        return "Access Denied", 403

    try:
        refresh_url = url_for("developer.stripe_connect_refresh", _external=True)
        return_url = url_for("developer.stripe_connect_return", _external=True)
        onboarding_url = create_connect_onboarding_link(current_user, refresh_url, return_url)
        return redirect(onboarding_url)
    except Exception as e:
        print(f"DEBUG: Stripe Connect refresh error: {e}")
        flash("Onboarding session expired. Please click connect again.", "error")
        return redirect(url_for("developer.developer_revenue"))


@developer_bp.route("/dashboard/stripe-connect/dashboard")
@login_required
def stripe_connect_dashboard():
    if current_user.role != "dev":
        return "Access Denied", 403

    if not current_user.stripe_connect_id:
        flash("You have not connected a Stripe account yet.", "error")
        return redirect(url_for("developer.developer_revenue"))

    try:
        login_url = create_connect_login_link(current_user)
        if login_url:
            return redirect(login_url)
        flash("Could not open Stripe Express Dashboard.", "error")
    except Exception as e:
        print(f"DEBUG: Stripe Connect dashboard error: {e}")
        flash(f"Stripe Dashboard error: {e}", "error")

    return redirect(url_for("developer.developer_revenue"))

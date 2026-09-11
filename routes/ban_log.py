from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import current_user, login_required
from sqlalchemy import or_

from extensions import db
from models.ban import UserBan, ModerationScanState
from models.user import User
from services.moderation_service import unban_user, execute_ban, run_moderation_scan

ban_log_bp = Blueprint("ban_log", __name__)


# public ban log wall of shame xD
@ban_log_bp.route("/bans", endpoint="index")
@ban_log_bp.route("/bans", endpoint="public_ban_log")
def index():
    # see who got kicked out and why xD
    filter_mode = request.args.get("filter", "all").strip().lower()
    search_q = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 20

    query = UserBan.query

    # search through the naughty list xD
    if search_q:
        query = query.filter(
            or_(
                UserBan.username.ilike(f"%{search_q}%"),
                UserBan.reason.ilike(f"%{search_q}%"),
                UserBan.offense_category.ilike(f"%{search_q}%"),
            )
        )

    # filter by permaban, 30 days or active xD
    if filter_mode == "permanent":
        query = query.filter(UserBan.ban_type == "permanent")
    elif filter_mode == "temporary":
        query = query.filter(UserBan.ban_type == "temporary")
    elif filter_mode == "active":
        query = query.filter(UserBan.is_active == True)

    query = query.order_by(UserBan.banned_at.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    bans = pagination.items

    # stats for the hero banner so people see we mean business xD
    total_bans = UserBan.query.count()
    active_bans = UserBan.query.filter_by(is_active=True).count()
    permanent_bans = UserBan.query.filter_by(ban_type="permanent").count()
    temporary_bans = UserBan.query.filter_by(ban_type="temporary").count()

    scan_state = ModerationScanState.query.first()

    return render_template(
        "bans.html",
        bans=bans,
        pagination=pagination,
        filter_mode=filter_mode,
        search_q=search_q,
        total_bans=total_bans,
        active_bans=active_bans,
        permanent_bans=permanent_bans,
        temporary_bans=temporary_bans,
        scan_state=scan_state,
    )


# easy alias redirect (:
@ban_log_bp.route("/ban-log")
def redirect_ban_log():
    return redirect(url_for("ban_log.index"))


# admins or devs can fire up the groq ai scanner on demand xD
@ban_log_bp.route("/admin/moderation/run-scan", methods=["POST"])
@login_required
def trigger_scan():
    if getattr(current_user, "role", "") != "admin" and getattr(current_user, "role", "") != "dev":
        abort(403)

    res = run_moderation_scan()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
        return jsonify(res)

    flash(
        f"AI moderation scan complete! Checked {res.get('items_scanned', 0)} items, "
        f"banned {res.get('bans_issued', 0)} users.",
        "success" if res.get("status") != "failed" else "error",
    )
    return redirect(request.referrer or url_for("ban_log.index"))


# only admins can pardon bans
@ban_log_bp.route("/admin/bans/<int:ban_id>/unban", methods=["POST"])
@login_required
def admin_unban(ban_id):
    if getattr(current_user, "role", "") != "admin":
        abort(403)

    success = unban_user(ban_id)
    if success:
        flash("User got pardoned! Welcome back to Sqush.", "success")
    else:
        flash("Could not find this ban entry or it is no longer active.", "error")
    return redirect(request.referrer or url_for("ban_log.index"))


# only admins can manually ban users; developers can only trigger the groq scan
@ban_log_bp.route("/admin/bans/manual", methods=["POST"])
@login_required
def admin_manual_ban():
    if getattr(current_user, "role", "") != "admin":
        abort(403)

    identifier = request.form.get("identifier", "").strip()
    severity = request.form.get("severity", "minor").strip()
    reason = request.form.get("reason", "").strip() or "Manual community violation"
    offense_category = request.form.get("offense_category", "custom").strip()

    if not identifier:
        flash("Please enter a username or email address.", "error")
        return redirect(url_for("ban_log.index"))

    # target either username or email
    user = User.query.filter(or_(User.username == identifier, User.email == identifier.lower())).first()

    if user:
        user_id = user.id
        email = user.email
        username = user.username
    else:
        user_id = None
        email = identifier.lower()
        username = identifier.split("@")[0]

    execute_ban(
        user_id=user_id,
        email=email,
        username=username,
        severity=severity,
        offense_category=offense_category,
        reason=reason,
        evidence_snippet=f"Manual ban by admin {current_user.username}",
        banned_by=f"Admin ({current_user.username})",
    )

    flash(f"Ban for {username} ({'Permanent' if severity == 'severe' else '30 day timeout'}) recorded successfully.", "success")
    return redirect(url_for("ban_log.index"))

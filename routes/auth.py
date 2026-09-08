import os
import re
import secrets
from urllib.parse import urlencode
from datetime import datetime, timezone
import requests
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, flash, session
from flask_login import login_user, logout_user, current_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from itsdangerous import SignatureExpired, BadSignature
from firebase_admin import auth as firebase_auth

from extensions import db, limiter, email_serializer, FIREBASE_ENABLED
from models.user import User, LoginOTP
from services.mail_service import send_verification_email, send_email_change_verification, send_login_otp
from services.cart_service import _merge_guest_cart
from services.auth_service import connected_login_methods_count
from services.badge_service import sync_user_badges
import config

auth_bp = Blueprint("auth", __name__)


#authentication routes.
@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("10/hour", methods=["POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]
        role = request.form["role"]
        # checkbox is checked by default in the template.
        require_email_confirmation = "email_confirmation" in request.form

        if User.query.filter_by(username=username).first() or User.query.filter_by(email=email).first():
            flash("Username or Email exists! Be faster next time xD", "error")
            return redirect(url_for("register"))

        new_user = User(username=username, email=email, role=role, has_password=True)
        new_user.set_password(password)
        new_user.email_verified = not require_email_confirmation
        db.session.add(new_user)
        db.session.commit()
        sync_user_badges(new_user)

        if require_email_confirmation:
            send_verification_email(new_user)
            flash("Almost there! Check your inbox and confirm your email address before logging in (:", "success")
        else:
            flash("Account created! You can log in now.", "success")

        return redirect(url_for("login"))
    return render_template("register.html")


#Lets Lock in
@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10/minute", methods=["POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password):
            flash("Invalid username or password", "error")
            return redirect(url_for("login"))

        if not user.email_verified:
            flash("Please confirm your email address first. Check your mailbox (: Didn't get an email?", "error")
            session["pending_verification_email"] = user.email
            return redirect(url_for("login"))

        # if the user turned 2FA off in their settings we skip the code mail entirely.
        if not user.two_fa_enabled:
            login_user(user, remember=True)
            _merge_guest_cart(user)
            if user.role == "dev":
                return redirect(url_for("developer_dashboard"))
            return redirect(url_for("profile", username=user.username))

        # password is correct, mail is verified -> now the 2FA gate.
        # login_user() only happens AFTER the code from verify_2fa() checks out.
        send_login_otp(user)
        session["pending_2fa_user_id"] = user.id
        return redirect(url_for("verify_2fa"))

    return render_template(
        "login.html",
        firebase_config=config.FIREBASE_WEB_CONFIG,
        firebase_enabled=FIREBASE_ENABLED,
        hackclub_enabled=config.HACKCLUB_ENABLED,
    )


# Hack Club OAuth routes
@auth_bp.route("/auth/hackclub/login")
def hackclub_login():
    if not config.HACKCLUB_CLIENT_ID or not config.HACKCLUB_CLIENT_SECRET:
        flash("Hack Club login is not configured on this server.", "error")
        return redirect(url_for("login"))

    params = {
        "client_id": config.HACKCLUB_CLIENT_ID,
        "redirect_uri": config.HACKCLUB_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email",
    }

    auth_url = f"{config.HACKCLUB_AUTH_BASE}/oauth/authorize?{urlencode(params)}"
    return redirect(auth_url)


# Same OAuth dance as hackclub_login, but started from a logged-in session (Settings page)
# so the callback knows to LINK the account instead of logging someone in/registering.
@auth_bp.route("/settings/link/hackclub")
@login_required
def link_hackclub():
    if not config.HACKCLUB_CLIENT_ID or not config.HACKCLUB_CLIENT_SECRET:
        flash("Hack Club login is not configured on this server.", "error")
        return redirect(url_for("settings"))

    if current_user.hackclub_id:
        flash("Your account is already linked with Hack Club.", "info")
        return redirect(url_for("settings"))

    session["hackclub_link_user_id"] = current_user.id

    params = {
        "client_id": config.HACKCLUB_CLIENT_ID,
        "redirect_uri": config.HACKCLUB_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email",
    }

    auth_url = f"{config.HACKCLUB_AUTH_BASE}/oauth/authorize?{urlencode(params)}"
    return redirect(auth_url)


@auth_bp.route("/auth/hackclub/callback")
@limiter.limit("15/minute")
def hackclub_callback():
    # if this was started from /settings/link/hackclub, we're linking to an existing
    # account instead of logging in / registering a new one. Pop it once at the top so
    # every early-return below (error cases) also lands back on the right page.
    link_user_id = session.pop("hackclub_link_user_id", None)
    fail_redirect = url_for("settings") if link_user_id else url_for("login")

    error = request.args.get("error")
    if error:
        print("DEBUG: Hack Club OAuth error:", error)
        flash("Hack Club login failed or was cancelled.", "error")
        return redirect(fail_redirect)

    code = request.args.get("code")
    if not code:
        print("DEBUG: No OAuth code returned:", dict(request.args))
        flash("Hack Club login failed: no authorization code returned.", "error")
        return redirect(fail_redirect)

    try:
        token_res = requests.post(
            f"{config.HACKCLUB_AUTH_BASE}/oauth/token",
            json={
                "client_id": config.HACKCLUB_CLIENT_ID,
                "client_secret": config.HACKCLUB_CLIENT_SECRET,
                "redirect_uri": config.HACKCLUB_REDIRECT_URI,
                "code": code,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        token_res.raise_for_status()

        access_token = token_res.json().get("access_token")
        if not access_token:
            raise ValueError("No access token returned")

        me_res = requests.get(
            f"{config.HACKCLUB_AUTH_BASE}/api/v1/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        me_res.raise_for_status()

    except (requests.RequestException, ValueError) as e:
        print(f"DEBUG: Hack Club OAuth error: {e}")
        flash("Hack Club login failed: could not authenticate with Hack Club.", "error")
        return redirect(fail_redirect)

    profile = me_res.json()
    identity = profile.get("identity") or {}
    email = (identity.get("primary_email") or "").strip().lower()
    # not 100% sure "id" is the field name here since I can't check the live API response,
    # so this is defensive - falls back to None and we just skip storing a hard identity link.
    hackclub_id = str(identity.get("id") or profile.get("id") or "").strip() or None

    if not email:
        print("DEBUG: Hack Club profile without primary_email:", profile)
        flash("Hack Club login failed: no email address was returned.", "error")
        return redirect(fail_redirect)

    # link mode: slap hack club onto the logged in user (:
    if link_user_id:
        target_user = db.session.get(User, link_user_id)
        if not target_user:
            flash("Your session expired, please try linking again.", "error")
            return redirect(url_for("login"))

        if hackclub_id:
            existing_owner = User.query.filter(
                User.hackclub_id == hackclub_id, User.id != target_user.id
            ).first()
            if existing_owner:
                flash("That Hack Club account is already linked to a different Sqush account.", "error")
                return redirect(url_for("settings"))

        target_user.hackclub_id = hackclub_id
        db.session.commit()
        flash("Hack Club account linked!", "success")
        return redirect(url_for("settings"))

    # normal mode: login or make a brand new account xD
    user = User.query.filter_by(email=email).first()

    if not user:
        username_source = email.split("@", 1)[0]
        base_username = re.sub(r"[^a-zA-Z0-9_]", "", username_source) or "hackclub_user"
        username = base_username[:64]
        suffix = 1

        while User.query.filter_by(username=username).first():
            suffix += 1
            username = f"{base_username[:64 - len(str(suffix))]}{suffix}"

        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(secrets.token_urlsafe(32)),
            email_verified=True,
            needs_username_setup=True,
            has_password=False,
            hackclub_id=hackclub_id,
        )
        db.session.add(user)
        db.session.commit()
    elif hackclub_id and not user.hackclub_id:
        # existing account, first time coming in through Hack Club -> remember the link
        user.hackclub_id = hackclub_id
        db.session.commit()

    login_user(user, remember=True)
    _merge_guest_cart(user)

    if user.needs_username_setup:
        return redirect(url_for("choose_username"))

    if user.role == "dev":
        return redirect(url_for("developer_dashboard"))

    return redirect(url_for("profile", username=user.username))


@auth_bp.route("/verify_email/<token>")
def verify_email(token):
    try:
        email = email_serializer.loads(token, salt="email-verify", max_age=60 * 60 * 24)  # 24h
    except SignatureExpired:
        flash("The confirmation link expired. Request a new one below.", "error")
        return redirect(url_for("login"))
    except BadSignature:
        flash("Wrong confirmation link", "error")
        return redirect(url_for("login"))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash("User not found", "error")
        return redirect(url_for("login"))

    if user.email_verified:
        flash("Your Email address is already confirmed! You can log in.", "info")
        return redirect(url_for("login"))

    user.email_verified = True
    db.session.commit()
    flash("Your Email address is confirmed! You can log in now.", "success")
    return redirect(url_for("login"))


@auth_bp.route("/verify_email_change/<token>")
def verify_email_change(token):
    try:
        data = email_serializer.loads(token, salt="email-change", max_age=60 * 60 * 24)  # 24h
    except SignatureExpired:
        flash("The confirmation link expired. Request the change again on the settings page", "error")
        return redirect(url_for("settings"))
    except BadSignature:
        flash("Wrong confirmation link", "error")
        return redirect(url_for("settings"))

    if data.get("user_id") != current_user.id:
        flash("This link doesn't belong to your account", "error")
        return redirect(url_for("settings"))

    new_email = data.get("new_email")
    if not new_email:
        return redirect(url_for("settings"))

    # someone else might have grabbed that address in the meantime
    if User.query.filter(User.email == new_email, User.id != current_user.id).first():
        flash("That Email address is already in use by another account", "error")
        return redirect(url_for("settings"))

    current_user.email = new_email
    current_user.email_verified = True
    db.session.commit()
    flash("Your new Email address is confirmed!", "success")
    return redirect(url_for("settings"))


@auth_bp.route("/resend_verification", methods=["POST"])
@limiter.limit("5/hour")
def resend_verification():
    email = request.form.get("email") or session.get("pending_verification_email")
    user = User.query.filter_by(email=email).first() if email else None
    if user and not user.email_verified:
        send_verification_email(user)
    # same message either way, don't leak which emails exist in the DB
    flash("When the Email address exist but isn't confirmed, we sent a new mail one!", "info")
    return redirect(url_for("login"))


@auth_bp.route("/login/verify-2fa", methods=["GET", "POST"])
@limiter.limit("8/minute", methods=["POST"])
def verify_2fa():
    user_id = session.get("pending_2fa_user_id")
    if not user_id:
        return redirect(url_for("login"))

    user = db.session.get(User, user_id)
    if not user:
        session.pop("pending_2fa_user_id", None)
        return redirect(url_for("login"))

    if request.method == "POST":
        code = request.form.get("code", "").strip()
        otp = LoginOTP.query.filter_by(user_id=user.id).order_by(LoginOTP.created_at.desc()).first()

        if not otp or otp.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            flash("The code expired. We sent a new one!", "error")
            send_login_otp(user)
            return redirect(url_for("verify_2fa"))

        if not check_password_hash(otp.code_hash, code):
            flash("False code! Try again.", "error")
            return redirect(url_for("verify_2fa"))

        db.session.delete(otp)
        db.session.commit()
        session.pop("pending_2fa_user_id", None)
        login_user(user, remember=True)
        _merge_guest_cart(user)

        if user.role == "dev":
            return redirect(url_for("developer_dashboard"))
        return redirect(url_for("profile", username=user.username))

    return render_template("verify_2fa.html", email=user.email)


@auth_bp.route("/login/resend-2fa", methods=["POST"])
@limiter.limit("5/hour")
def resend_2fa():
    user_id = session.get("pending_2fa_user_id")
    if user_id:
        user = db.session.get(User, user_id)
        if user:
            send_login_otp(user)
            flash("New code sent (;", "info")
    return redirect(url_for("verify_2fa"))


@auth_bp.route("/auth/google-login", methods=["POST"])
@limiter.limit("15/minute")
def google_login():
    # called via fetch
    if not FIREBASE_ENABLED:
        return jsonify({"error": "Google Login is not configured on this server"}), 503

    payload = request.get_json(silent=True) or {}
    id_token = payload.get("idToken")
    link_mode = payload.get("mode") == "link"

    if not id_token:
        return jsonify({"error": "Missing idToken"}), 400

    try:
        decoded = firebase_auth.verify_id_token(id_token)
    except Exception as e:
        print(f"DEBUG: Firebase token error: {e}")
        return jsonify({"error": "Invalid or expired token"}), 401

    email = decoded.get("email")
    uid = decoded.get("uid")
    display_name = decoded.get("name") or (email.split("@")[0] if email else "gamer")

    if not email:
        return jsonify({"error": "Google account has no email"}), 400

    # link mode: slap google onto the logged in user (:
    if link_mode:
        if not current_user.is_authenticated:
            return jsonify({"error": "You need to be logged in to link an account"}), 401

        existing_owner = User.query.filter(
            User.firebase_uid == uid, User.id != current_user.id
        ).first()
        if existing_owner:
            return jsonify({"error": "That Google account is already linked to a different Sqush account"}), 409

        current_user.firebase_uid = uid
        db.session.commit()
        return jsonify({"status": "ok", "redirect": url_for("settings")})

    # normal mode: login or make a brand new account xD
    user = User.query.filter_by(firebase_uid=uid).first()
    if not user:
        user = User.query.filter_by(email=email).first()

    if not user:
        # brand new account, Google already vouches for the mail so no verification step needed
        base_username = secure_filename(display_name).replace(" ", "_") or "gamer"
        username = base_username
        counter = 1
        while User.query.filter_by(username=username).first():
            username = f"{base_username}{counter}"
            counter += 1

        user = User(username=username, email=email, role="user",
                    email_verified=True, firebase_uid=uid,
                    needs_username_setup=True,  # let them pick their own name on first login
                    has_password=False)
        # nobody logs in with this password
        user.set_password(os.urandom(16).hex())
        db.session.add(user)
        db.session.commit()
    elif not user.firebase_uid:
        user.firebase_uid = uid
        user.email_verified = True
        db.session.commit()

    # Google Sign in already is strong so we skip 2fa
    login_user(user, remember=True)

    if user.needs_username_setup:
        redirect_url = url_for("choose_username")
    else:
        redirect_url = url_for("developer_dashboard") if user.role == "dev" else url_for("profile", username=user.username)
    return jsonify({"status": "ok", "redirect": redirect_url})


@auth_bp.route("/choose-username", methods=["GET", "POST"])
@login_required
def choose_username():
    #only relevant right after the first Google login
    if request.method == "POST":
        new_username = request.form.get("username", "").strip()

        if len(new_username) < 3 or len(new_username) > 64:
            flash("Your username needs to be between 3 and 64 characters", "error")
            return redirect(url_for("choose_username"))

        existing = User.query.filter(User.username == new_username, User.id != current_user.id).first()
        if existing:
            flash("That username is already taken, be more creative (;", "error")
            return redirect(url_for("choose_username"))

        current_user.username = new_username
        current_user.needs_username_setup = False
        db.session.commit()
        flash("Nice, that's your username now!", "success")

        if current_user.role == "dev":
            return redirect(url_for("developer_dashboard"))
        return redirect(url_for("profile", username=current_user.username))

    return render_template("choose_username.html", suggested_username=current_user.username)


#The one help page for everything account related
@auth_bp.route("/settings")
@login_required
def settings():
    return render_template(
        "settings.html",
        firebase_config=config.FIREBASE_WEB_CONFIG,
        firebase_enabled=FIREBASE_ENABLED,
        hackclub_enabled=config.HACKCLUB_ENABLED,
    )


@auth_bp.route("/settings/username", methods=["POST"])
@login_required
def update_username():
    new_username = request.form.get("username", "").strip()

    if len(new_username) < 3 or len(new_username) > 64:
        flash("Your username needs to be between 3 and 64 characters", "error")
        return redirect(url_for("settings"))

    existing = User.query.filter(User.username == new_username, User.id != current_user.id).first()
    if existing:
        flash("That username is already taken", "error")
        return redirect(url_for("settings"))

    old_username = current_user.username
    current_user.username = new_username
    db.session.commit()
    flash(f"Username changed from {old_username} to {new_username}!", "success")
    return redirect(url_for("settings"))


#uff why the hell
@auth_bp.route("/settings/email", methods=["POST"])
@login_required
def update_email():
    new_email = request.form.get("email", "").strip().lower()

    if not new_email or "@" not in new_email:
        flash("That doesn't look like a valid Email address", "error")
        return redirect(url_for("settings"))

    if new_email == current_user.email:
        flash("That's already your Email address (:", "info")
        return redirect(url_for("settings"))

    if User.query.filter(User.email == new_email, User.id != current_user.id).first():
        flash("That Email address is already used by another account", "error")
        return redirect(url_for("settings"))

    send_email_change_verification(current_user, new_email)
    flash("We sent a confirmation link to your new Email address. Click it to make the change final!", "success")
    return redirect(url_for("settings"))


@auth_bp.route("/settings/password", methods=["POST"])
@login_required
@limiter.limit("10/hour")
def update_password():
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    new_password_repeat = request.form.get("new_password_repeat", "")

    if not current_user.check_password(current_password):
        flash("Your current password is wrong", "error")
        return redirect(url_for("settings"))

    if len(new_password) < 8:
        flash("Your new password needs at least 8 characters", "error")
        return redirect(url_for("settings"))

    if new_password != new_password_repeat:
        flash("The new passwords don't match", "error")
        return redirect(url_for("settings"))

    current_user.set_password(new_password)
    db.session.commit()
    flash("Password changed!", "success")
    return redirect(url_for("settings"))


@auth_bp.route("/settings/2fa/toggle", methods=["POST"])
@login_required
def toggle_2fa():
    current_user.two_fa_enabled = not current_user.two_fa_enabled
    db.session.commit()
    if current_user.two_fa_enabled:
        flash("2FA is now enabled. You'll get a login code by mail from now on.", "success")
    else:
        flash("2FA is now disabled. Careful out there (:", "info")
    return redirect(url_for("settings"))


@auth_bp.route("/settings/set-password", methods=["POST"])
@login_required
def set_password():
    # for accounts that signed up through Google/Hack Club and never had a real password
    if current_user.has_password:
        flash("You already have a password set. Use the change password form instead.", "error")
        return redirect(url_for("settings"))

    new_password = request.form.get("new_password", "")
    new_password_repeat = request.form.get("new_password_repeat", "")

    if len(new_password) < 8:
        flash("Your new password needs at least 8 characters", "error")
        return redirect(url_for("settings"))

    if new_password != new_password_repeat:
        flash("The new passwords don't match", "error")
        return redirect(url_for("settings"))

    current_user.set_password(new_password)
    current_user.has_password = True
    db.session.commit()
    flash("Password set! You can now log in with your username and password too.", "success")
    return redirect(url_for("settings"))


@auth_bp.route("/settings/unlink/google", methods=["POST"])
@login_required
def unlink_google():
    if not current_user.firebase_uid:
        return redirect(url_for("settings"))

    if connected_login_methods_count(current_user) <= 1:
        flash("Can't unlink your last login method. Set a password or link another account first.", "error")
        return redirect(url_for("settings"))

    current_user.firebase_uid = None
    db.session.commit()
    flash("Google account unlinked.", "info")
    return redirect(url_for("settings"))


@auth_bp.route("/settings/unlink/hackclub", methods=["POST"])
@login_required
def unlink_hackclub():
    if not current_user.hackclub_id:
        return redirect(url_for("settings"))

    if connected_login_methods_count(current_user) <= 1:
        flash("Can't unlink your last login method. Set a password or link another account first.", "error")
        return redirect(url_for("settings"))

    current_user.hackclub_id = None
    db.session.commit()
    flash("Hack Club account unlinked.", "info")
    return redirect(url_for("settings"))


# You shouldn't even wanna do this ):
@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("home"))

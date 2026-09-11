import os
import json
from dotenv import load_dotenv

# Stripe API Keys.
load_dotenv()

#secruity first huh? and then the Database
SECRET_KEY = os.environ.get("SECRET_KEY", "fallback_secret_key_if_not_set")
_db_uri = os.environ.get("DATABASE_URL", "sqlite:///db.sqlite3")
if _db_uri.startswith("postgres://"):
    _db_uri = _db_uri.replace("postgres://", "postgresql://", 1)
SQLALCHEMY_DATABASE_URI = _db_uri
SQLALCHEMY_TRACK_MODIFICATIONS = False

#Directory for Videos , Pictures and REAL GAME FILES.
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "static/uploads")
AVATAR_FOLDER = os.environ.get("AVATAR_FOLDER", "static/avatars")

os.makedirs(AVATAR_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# r2 storage for huge games so i don't go broke (:
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME")
R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")
R2_ENABLED = bool(R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_BUCKET_NAME)


def _get_r2_endpoint():
    raw = os.environ.get("R2_ENDPOINT_URL") or R2_ACCOUNT_ID or ""
    import re
    # strip accidental https://, http://, https/, etc. so we don't get double https://https/ xD
    cleaned = re.sub(r"^(https?[:/]+)+", "", raw.strip(), flags=re.IGNORECASE).strip("/")
    if not cleaned:
        return ""
    if ".r2.cloudflarestorage.com" in cleaned:
        return f"https://{cleaned}"
    return f"https://{cleaned}.r2.cloudflarestorage.com"


R2_ENDPOINT_URL = _get_r2_endpoint()

# slap bots in the face xD
TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY")
TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY")
TURNSTILE_ENABLED = bool(TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY)

# hack club login stuff
HACKCLUB_CLIENT_ID = os.environ.get("HACKCLUB_CLIENT_ID")
HACKCLUB_CLIENT_SECRET = os.environ.get("HACKCLUB_CLIENT_SECRET")
HACKCLUB_REDIRECT_URI = os.environ.get(
    "HACKCLUB_REDIRECT_URI",
    "http://localhost:5000/auth/hackclub/callback",
)
HACKCLUB_AUTH_BASE = "https://auth.hackclub.com"
# so we know if the button should even show up (:
HACKCLUB_ENABLED = bool(HACKCLUB_CLIENT_ID and HACKCLUB_CLIENT_SECRET)

stripe_keys = {
    "secret_key": os.environ.get("STRIPE_SECRET_KEY"),
    "publishable_key": os.environ.get("STRIPE_PUBLISHABLE_KEY"),
}

#juicy money XD
STRIPE_SECRET_KEY = stripe_keys["secret_key"]
STRIPE_PUBLISHABLE_KEY = stripe_keys["publishable_key"]
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

# revenue split so devs get their cash (:
PLATFORM_FEE_PERCENT = float(os.environ.get("PLATFORM_FEE_PERCENT", "10.0"))  # 10% sqush keeps
DEV_PAYOUT_PERCENT = float(os.environ.get("DEV_PAYOUT_PERCENT", "90.0"))     # 90% dev cut
TIP_PLATFORM_FEE_PERCENT = float(os.environ.get("TIP_PLATFORM_FEE_PERCENT", "0.0")) # 0% on tips (100% goes to the dev (: )

MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", MAIL_USERNAME)

FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
FIREBASE_SERVICE_ACCOUNT_PATH = os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH", "firebase-service-account.json")

FIREBASE_WEB_CONFIG = {
    "apiKey": os.environ.get("FIREBASE_API_KEY", ""),
    "authDomain": os.environ.get("FIREBASE_AUTH_DOMAIN", ""),
    "projectId": os.environ.get("FIREBASE_PROJECT_ID", ""),
    "appId": os.environ.get("FIREBASE_APP_ID", ""),
}

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

# only zips and exes for game downloads, everything else gets kicked out instantly xD
ALLOWED_GAME_EXTENSIONS = {"zip", "exe"}
# scanning games so nobody uploads malware lol
CLAMAV_ENABLED = os.environ.get("CLAMAV_ENABLED", "false").lower() == "true"
CLAMAV_HOST = os.environ.get("CLAMAV_HOST", "localhost")
CLAMAV_PORT = int(os.environ.get("CLAMAV_PORT", 3310))

RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

# Groq AI content moderation config (:
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_MODERATION_INTERVAL_SECONDS = int(os.environ.get("GROQ_MODERATION_INTERVAL_SECONDS", 60))  # 60 seconds
AI_MODERATION_ENABLED = os.environ.get("AI_MODERATION_ENABLED", "true").lower() == "true"


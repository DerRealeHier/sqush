import json
import os
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from itsdangerous import URLSafeTimedSerializer
import stripe
import firebase_admin
from firebase_admin import credentials as firebase_credentials, auth as firebase_auth
from flask_socketio import SocketIO
import config
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
socketio = SocketIO(cors_allowed_origins="*")

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" in type(dbapi_connection).__module__:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-64000")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

#Initiliaze Login
login_manager = LoginManager()
login_manager.login_view = "login"  #YOU BETTER LOGIN

mail = Mail()

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=config.RATELIMIT_STORAGE_URI,
    default_limits=[],  # no blanket limit, we set limits per oute below
)

#Yea I need that
migrate = Migrate()

email_serializer = URLSafeTimedSerializer(config.SECRET_KEY)

# Stripe API Keys.
stripe.api_key = config.STRIPE_SECRET_KEY

FIREBASE_ENABLED = False

if config.FIREBASE_SERVICE_ACCOUNT_JSON:
    try:
        firebase_cred = firebase_credentials.Certificate(json.loads(config.FIREBASE_SERVICE_ACCOUNT_JSON))
        firebase_admin.initialize_app(firebase_cred)
        FIREBASE_ENABLED = True
    except (json.JSONDecodeError, ValueError) as e:
        print(f"DEBUG: FIREBASE_SERVICE_ACCOUNT_JSON is broken, Google Login stays disabled: {e}")
elif os.path.exists(config.FIREBASE_SERVICE_ACCOUNT_PATH):
    firebase_cred = firebase_credentials.Certificate(config.FIREBASE_SERVICE_ACCOUNT_PATH)
    firebase_admin.initialize_app(firebase_cred)
    FIREBASE_ENABLED = True
else:
    print("DEBUG: No Firebase credentials found. Google Login button stays hidden")

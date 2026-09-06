# sqush.io

**sqush.io** is an open source indie game store platform. Think itch.io, but with a better user experience and more fun to use. Developers can publish and sell their games, players can browse, buy, review, gift games and message each other or game developers, and everyone can connect socially.

---

## Features

| Category | Features                                                                                           |
|---|----------------------------------------------------------------------------------------------------|
| **Auth** | Email/password registration, email verification, OTP 2FA, Google login (Firebase), Hack Club OAuth |
| **Store** | Browse games, search & filter by tags, featured/popular/recommended listings                       |
| **Game pages** | Screenshots, videos, reviews with upvotes, developer update posts with comments, unified action pills (Wishlist, Follow, Roadmap, Gift, Message Dev, Tip Dev), and dedicated Buy Box with demo downloads |
| **Roadmaps** | Public interactive Kanban boards (Planned, In Progress, Done), community feature upvoting, bug reporting, drag-and-drop card status management for devs, and item discussion threads |
| **Purchases** | Stripe checkout, cart (guest + logged in), wishlists, game gifting, Tip Jar donations              |
| **Bundles** | Multi-game bundles with collaborator roles, bundle-specific pricing                                |
| **Library** | Owned games, download game files, playtime tracking                                                |
| **Social** | Friends, profile pages, profile comments, notifications, collections                               |
| **Messaging** | Direct messaging (user-to-user & user-to-dev), conversation threads, game inquiries, unread badges  |
| **Developer** | Dashboard, upload game files (ZIP/EXE), sales and tip analytics, game stats, roadmap item management |
| **Security** | Rate limiting, ClamAV malware scanning for uploaded files                                          |
| **Badges** | User badge system with featured badge on profile (including Tip Jar Hero)                          |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, Flask 3 |
| Database | SQLite (via SQLAlchemy 2 + Flask-Migrate / Alembic) |
| Auth | Flask-Login, Firebase Admin SDK, itsdangerous (email tokens) |
| Payments | Stripe |
| Email | Flask-Mail (Gmail SMTP) |
| Rate limiting | Flask-Limiter |
| File scanning | ClamAV (optional) |
| Frontend | Jinja2 templates, vanilla JS |

---

## Project Structure

```
sqush.io/
├── app.py              # App factory & entry point
├── config.py           # All config loaded from .env
├── extensions.py       # Flask extension instances (db, login, mail, stripe, firebase, ...)
├── models/
│   ├── user.py         # User, Friendship, Notification, ProfileComment, LoginOTP, UserBadge
│   ├── game.py         # Game, Screenshot, Video, Review, ReviewVote, GameUpdate, GameStats, ...
│   ├── commerce.py     # Purchase, Wishlist, CartItem, Gift, Tip
│   ├── bundle.py       # Bundle, BundleGame, BundleCollaborator
│   ├── collection.py   # Collection, CollectionGame
│   ├── message.py      # DirectMessage (user-to-user & user-to-dev inquiries)
│   └── roadmap.py      # RoadmapItem, RoadmapVote, RoadmapComment
├── routes/
│   ├── auth.py         # Register, login, logout, OAuth (Google, Hack Club), 2FA
│   ├── main.py         # Home, store, game detail pages
│   ├── cart.py         # Cart management (guest & logged-in)
│   ├── checkout.py     # Stripe checkout, webhooks, gifting, Tip Jar
│   ├── library.py      # User library, downloads
│   ├── social.py       # Profiles, friends, collections, notifications
│   ├── developer.py    # Developer dashboard, game upload/edit, analytics, revenue and tips
│   ├── messages.py     # Direct messaging, inbox, conversation threads, unread counters
│   └── roadmap.py      # Public Kanban boards, feature voting, bug reporting, card discussions
├── services/
│   ├── auth_service.py   # load_user, login helpers
│   ├── badge_service.py  # Badge award logic
│   ├── cart_service.py   # Cart token & merge helpers
│   ├── file_service.py   # File upload & ClamAV scan
│   ├── game_service.py   # Recommendations, stats, tags, tip calculations
│   ├── mail_service.py   # Transactional email templates
│   └── payment_service.py# Stripe checkout & fulfillment (games, gifts, tips)
├── templates/          # Jinja2 HTML templates (including game_roadmap.html, developer_revenue.html)
├── static/             # CSS, JS, images, uploaded files
├── tests/              # Automated test suites (test_roadmap.py)
└── migrations/         # Alembic database migrations
```

---

## Local Setup

### 1. Prerequisites

- **Python 3.11+**
- **pip** or a virtual environment manager
- A **Stripe** account (test mode is fine)
- A **Gmail** account with an [App Password](https://myaccount.google.com/apppasswords) for SMTP
- *(Optional)* A **Firebase** project for Google login
- *(Optional)* A **Hack Club** OAuth app for Hack Club login
- *(Optional)* **ClamAV** daemon running locally for malware scanning

### 2. Clone & create virtual environment

```bash
git clone https://github.com/your-org/sqush.io.git
cd sqush.io

python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

> If there is no `requirements.txt` yet, generate one with:
> ```bash
> pip freeze > requirements.txt
> ```

### 4. Configure environment variables

Create a `.env` file in the project root. Copy the block below and fill in your values:

```dotenv
# Flask
SECRET_KEY=

# Stripe (https://dashboard.stripe.com/test/apikeys)
STRIPE_SECRET_KEY=
STRIPE_PUBLISHABLE_KEY=
STRIPE_WEBHOOK_SECRET=

# Email: Gmail with App Password (https://myaccount.google.com/apppasswords)
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=
MAIL_PASSWORD=
MAIL_DEFAULT_SENDER=

# Firebase / Google login (optional | leave empty to hide the Google button)
# Either paste the full service-account JSON inline …
FIREBASE_SERVICE_ACCOUNT_JSON=
# … or point to a JSON file on disk:
# FIREBASE_SERVICE_ACCOUNT_PATH=firebase-service-account.json
FIREBASE_API_KEY=
FIREBASE_AUTH_DOMAIN=
FIREBASE_PROJECT_ID=
FIREBASE_APP_ID=

# Hack Club OAuth (optional)
HACKCLUB_CLIENT_ID=
HACKCLUB_CLIENT_SECRET=
HACKCLUB_REDIRECT_URI=http://localhost:5000/auth/hackclub/callback

# ClamAV malware scanning (optional | set to true to enable)
CLAMAV_ENABLED=false
CLAMAV_HOST=localhost
CLAMAV_PORT=3310

# Rate-limiter storage (memory:// for dev, redis:// for production)
RATELIMIT_STORAGE_URI=memory://
```

### 5. Initialise the database

```bash
flask db upgrade
```

If you run for the very first time without any migration history, you can also just start the app: `db.create_all()` runs automatically on startup.

### 6. Run the development server

```bash
python app.py
```

The app will be available at **http://localhost:5000**.

---

## Stripe Setup (local webhooks)

To test purchase flows locally, forward Stripe webhook events to your dev server:

```bash
# Install the Stripe CLI (https://stripe.com/docs/stripe-cli)
stripe listen --forward-to localhost:5000/checkout/webhook
```

Copy the webhook signing secret printed by the CLI and add it as `STRIPE_WEBHOOK_SECRET` in your `.env`.

---

## Optional: ClamAV (malware scanning)

Game file uploads (ZIP/EXE) can be scanned automatically. To enable:

1. Install ClamAV and start `clamd` (default port 3310).
2. Set `CLAMAV_ENABLED=true` in `.env`.

Without ClamAV the upload still works | scanning is simply skipped.

---

## Database Migrations

This project uses [Flask-Migrate](https://flask-migrate.readthedocs.io/) (Alembic).

```bash
# Create a new migration after model changes
flask db migrate -m "describe your change"

# Apply pending migrations
flask db upgrade

# Roll back one revision
flask db downgrade
```

---

## Testing

Run tests using Python's built-in unittest runner:

```bash
# Run all tests
python -m unittest discover -s tests

# Run roadmap test suite
python -m unittest tests/test_roadmap.py
```

---

## Contributing

1. Fork the repo and create a feature branch.
2. Follow the existing code style.
3. Open a pull request with a clear description of your changes.

---

## License

This project is licensed under the terms of the [LICENSE](LICENSE) file included in this repository.

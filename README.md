# sqush

An indie game marketplace (oviuosly not from a big corp) where you can buy games, review them and even publish your own.

![sqush](static/images/pixel_art.png)

 **[live demo at sqush.dev](https://sqush.dev)**

> **Demo  mode:** The live site is loaded with test games and runs in Stripe test mode. You don't need real money to try anything. Just grab the test card right from the footer (`4242 4242 4242 4242`, Exp `12/34`, CVC `123`) to buy games, test developer payouts, and unlock card drops. (pinky promise)

---

## Quick start

The fastest way to try sqush is the live link above. If you want to run it on your own machine:

```bash
git clone https://github.com/DerRealeHier/sqush.git && cd sqush
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000` in your browser. The app starts right up with SQLite and comes pre seeded with 30+ demo games and cover art ready to test (3 of these test game seeds have handdrawn covers in paint, every other is done with a script that just adds the title random background color, a basic comic design and then its finished).

---

## Features

Here is everything built into sqush that you can try out:

### Storefront and Game Pages
- **Game Discovery:** Browse games with tag and genre filtering, search, and featured / popular / recommended sections.
- **Dynamic Day/Night Theme:** Header banner automatically switches between custom day and night pixel artwork based on the user's local hour (with a manual HUD toggle switch).
- **Rich Game Pages:** Screenshots, gameplay trailers/videos, user reviews with upvotes, developer devlog update posts with comment threads, and dedicated Buy Box with demo downloads.
- **Quick Action Pills:** Wishlist, Follow, View Roadmap, Gift, Message Developer, and Tip Jar right from the game header.
- **Multi-Game Bundles:** Multi-game bundles with custom bundle pricing and collaborator roles for multi-dev revenue sharing.

### Purchases and Stripe Connect 
- **Automated Developer Payouts:** Developers connect their Stripe account with Stripe Connect Express. On every game sale, 90% routes directly to the creator, while 10% is being kept as a platform fee.
- **100% Tip Jar:** Players can tip creators directly with 0% platform fee.
- **Multi Developer Cart Checkout:** Add games from multiple different developers to a single cart. The checkout automatically calculates the splits and issues individual transfers to each developer in the background.
- **Retroactive Backlog Payouts:** If a developer sells games before completing their Stripe KYC onboarding, earnings are held as `pending` and automatically swept to their account the second they finish onboarding in `/dashboard/revenue`.
- **Game Gifting and Wishlists:** Buy games as gifts with redeemable gift codes, send gifts directly, and keep track of games on your personal wishlist.

### Public Interactive Roadmaps
- **Public Kanban Boards:** Every game has an interactive board with Planned, In Progress, and Done columns.
- **Community Feature Voting and Bug Reports:** Players upvote feature cards, submit bug reports, and can discuss roadmap items in dedicated card threads.
- **Dev Status Management:** Developers can drag and drop or update card statuses in real time to keep players in the loop.

### Collectible Trading Cards & Inventory
- **Card Pack Drops:** Buying games or opening card packs drops digital trading cards across different rarity tiers (Common, Rare, Holographic, Secret) Sorry for the naming I played too much brainrot games.
- **Inventory & Trading:** Inspect your card collection in your inventory and trade cards directly with friends through direct messages (including free gifts for homies).

### Social and Messaging
- **Direct Messaging:** Direct messaging between users and game developers.
- **Profiles and Communities:** User profile pages with custom avatars, friend lists, profile wall comments and owned game collections.
- **Profile Badges:** User badge system with customizable featured badges displayed on your profile.

### Developer Dashboard and Infrastructure
- **Developer Hub:** Developer dashboard to upload game builds (ZIP/EXE), edit game metadata, view live sales and tip analytics, and track game stats (I know crazy right?).
- **Cloudflare R2 Storage:** Yeah I'm using that for hosting games. You don't need that. You can use other services for the database.
- **Security & Malware Scanning:** Optional ClamAV antivirus scanning for game uploads, rate limiting via Flask Limiter, and Cloudflare Turnstile bot protection (A bit of over engineering, this Store cant even handle 1000 games. at least I think so=)
- **Flexible Auth:** Email/password registration with email verification, OTP 2FA, Google login (Firebase), and Hack Club OAuth.

---

## Tech Stack

- **Backend:** Python 3.11+, Flask 3, SQLAlchemy 2, Flask-Migrate (Alembic)
- **Database:** SQLite (default/local) or PostgreSQL
- **Payments:** Stripe and Stripe Connect Express
- **File Storage:** Cloudflare R2 (S3 compatible) with local filesystem fallback. You don't need that you can use other services (But please don't)
- **Auth:** Flask Login, Firebase Admin SDK (Google login), Hack Club OAuth.
- **Email:** Flask Mail (SMTP / Resend API)
- **Security:** Flask Limiter, Cloudflare Turnstile, ClamAV (optional)
- **Frontend:** Jinja2 templates, vanilla JavaScript, custom retro CSS with pixel snapping

---

## Project Structure

```
sqush/
├── app.py              
├── config.py          
├── extensions.py     
├── models/
│   ├── user.py        
│   ├── game.py    
│   ├── commerce.py     
│   ├── bundle.py       
│   ├── collection.py   
│   ├── message.py     
│   └── roadmap.py      
├── routes/
│   ├── auth.py        
│   ├── main.py       
│   ├── cart.py          
│   ├── checkout.py   
│   ├── library.py     
│   ├── social.py     
│   ├── developer.py   
│   ├── messages.py     
│   └── roadmap.py      
├── services/
│   ├── auth_service.py   
│   ├── badge_service.py  
│   ├── cart_service.py   
│   ├── file_service.py   
│   ├── game_service.py   
│   ├── mail_service.py   
│   └── payment_service.py
├── templates/          
├── static/             
├── tests/          
└── migrations/         
```


If you somehow end up with the wrong project structure. (That shouldn't happen.) But better safe then sorry.
Made with https://azad-sl.github.io/GitTree/

---


## Running locally

### What you need (Not a 5090.)
- **Python 3.11+**
- A free **Stripe** account (test mode is all you need)
- *(Optional)* A Gmail account or Resend API key for sending emails
- *(Optional)* Firebase / Hack Club credentials for OAuth

### 1. Configure environment variables
Copy the example environment file:

```bash
cp .env.example .env
```

The defaults work out of the box for local browsing using SQLite. To test checkout and developer onboarding, paste your Stripe test keys into `.env`:

```dotenv
SECRET_KEY=dev-secret-key-change-in-production
DATABASE_URL=sqlite:///db.sqlite3

# Stripe test keys (from dashboard.stripe.com/test/apikeys)
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Payout splits (defaults to 90% dev / 10% platform / 0% tip fee)
PLATFORM_FEE_PERCENT=10.0
DEV_PAYOUT_PERCENT=90.0
TIP_PLATFORM_FEE_PERCENT=0.0
```

### 2. Start the dev server

```bash
python app.py
```

Visit **`http://localhost:5000`**. The app automatically creates tables and loads the seed data on startup.

### 3. Testing Stripe webhooks locally (optional)
To test checkout fulfillment and Stripe Connect sync locally, forward webhook events:

```bash
# Install the Stripe CLI (https://stripe.com/docs/stripe-cli)
stripe listen --forward-to localhost:5000/checkout/webhook --events checkout.session.completed,account.updated
```

Copy the `whsec_...` secret printed by the Stripe CLI into `STRIPE_WEBHOOK_SECRET` in your `.env`.

---

## How it works (tech choices and tradeoffs)

Building an indie store with "real payments", creator payouts, and big game files brought up a few fun challenges:

- **Destination Charges vs. Multi Seller Transfers:**
  When someone buys a single game or leaves a tip, sqush uses Stripe **Destination Charges** (`transfer_data.destination`). The money goes straight to the developer's connected Express account and never touches the platform balance.
  But Stripe doesn't allow multiple destination accounts in a single checkout session. When a buyer checks out a cart containing games from 3 different creators, sqush processes the transaction on the platform, then the webhook calculates each creator's cut and issues individual `stripe.Transfer.create` calls.
- **Handling devs who haven't onboarded yet (Backlog fulfillment):**
  A game can be published and bought before the developer finishes their Stripe onboarding. Instead of failing the payment, sqush tracks the earnings with `payout_status = 'pending'`. The moment the developer completes their onboarding at `/dashboard/revenue`, the webhook triggers a retroactive payout sweep that clears their pending balance automatically.

  The payment systems are so weird to work with. It really is just a hurdle. Cloudflare not mentioned cause who wants to hear about that.

---

## Running tests

```bash
# Run all test suites
python -m unittest discover -s tests

# Or run specific suites
python -m unittest tests/test_roadmap.py
python -m unittest tests/test_stripe_connect.py
python -m unittest tests/test_cards_inventory.py
```

These Tests should work and not confirm themselves.

---

## Database Migrations

This project uses [Flask Migrate](https://flask-migrate.readthedocs.io/) (It makes your life easier):

```bash
# Create a new migration after model changes
flask db migrate -m "describe your change"

# Apply pending migrations
flask db upgrade
```

---

## Credits & shoutouts

- **Hack Club** OAuth login.
- **Flask** & **SQLAlchemy** for a lightweight backend that stayed fun and fast to hack on.
- **Stripe** for making multiparty marketplace payouts actually feasible for indie developers (even tho it's still a hurdle to get through that).
- **Gemini** for making the testdata. (Not a single Interaction on this site is real for now (I also did much of that myself but Gemini was especially in the writing part). So there are entirely made up conversations so the platform feels more alife.)

## License 
Find it out yourself it's in the repo.
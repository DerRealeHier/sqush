import random
from datetime import datetime, timezone
from extensions import db
from models.user import User, Notification
from models.card import UserCard, CardTrade
from models.message import DirectMessage
from services.badge_service import grant_manual_badge, get_badge_definition


# all the shiny comic cards users can collect (:
# zero emojis, pure comic book attitude!
CARD_DEFINITIONS = {
    # Common tier (60% pull chance)
    "squshy_slime": {
        "key": "squshy_slime",
        "name": "Squshy The Blob",
        "subtitle": "Indie Hero & Mascot",
        "series": "Sqush Genesis Vol. 1",
        "rarity": "common",
        "power": 120,
        "defense": 85,
        "icon": "bi-shield-shaded",
        "bg_color": "#1e293b",
        "accent_color": "#38bdf8",
        "flavor": "Bouncy, resilient, and ready to sqush any bug in production.",
    },
    "dev_coffee": {
        "key": "dev_coffee",
        "name": "Midnight Brew",
        "subtitle": "Essential Elixir",
        "series": "Sqush Genesis Vol. 1",
        "rarity": "common",
        "power": 95,
        "defense": 60,
        "icon": "bi-cup-hot-fill",
        "bg_color": "#3b2518",
        "accent_color": "#f59e0b",
        "flavor": "Lukewarm caffeine that turns stack traces into shipped features.",
    },
    "pixel_paladin": {
        "key": "pixel_paladin",
        "name": "Pixel Paladin",
        "subtitle": "8-Bit Defender",
        "series": "Sqush Genesis Vol. 1",
        "rarity": "common",
        "power": 140,
        "defense": 150,
        "icon": "bi-controller",
        "bg_color": "#1f2937",
        "accent_color": "#10b981",
        "flavor": "Armed with an 8-bit broadsword and a CRT monitor shield.",
    },
    "glitch_gremlin": {
        "key": "glitch_gremlin",
        "name": "Glitch Gremlin",
        "subtitle": "Chaos Entity",
        "series": "Sqush Genesis Vol. 1",
        "rarity": "common",
        "power": 110,
        "defense": 70,
        "icon": "bi-bug-fill",
        "bg_color": "#371b2e",
        "accent_color": "#ec4899",
        "flavor": "It is not a bug, it is an undocumented gameplay mechanic.",
    },
    "rubber_duck": {
        "key": "rubber_duck",
        "name": "The Rubber Duck",
        "subtitle": "Senior Architecture Consultant",
        "series": "Sqush Genesis Vol. 1",
        "rarity": "common",
        "power": 80,
        "defense": 190,
        "icon": "bi-chat-heart-fill",
        "bg_color": "#2e2a14",
        "accent_color": "#eab308",
        "flavor": "Listens patiently to your rant until the solution reveals itself.",
    },

    # Rare tier (25% pull chance)
    "webhook_wizard": {
        "key": "webhook_wizard",
        "name": "Webhook Wizard",
        "subtitle": "Fintech Sorcerer",
        "series": "Sqush Genesis Vol. 1",
        "rarity": "rare",
        "power": 260,
        "defense": 210,
        "icon": "bi-lightning-charge-fill",
        "bg_color": "#1e1b4b",
        "accent_color": "#6366f1",
        "flavor": "Channels payouts directly into developer bank accounts without lag.",
    },
    "indie_maverick": {
        "key": "indie_maverick",
        "name": "Solo Developer",
        "subtitle": "One-Person Studio",
        "series": "Sqush Genesis Vol. 1",
        "rarity": "rare",
        "power": 290,
        "defense": 240,
        "icon": "bi-laptop-fill",
        "bg_color": "#064e3b",
        "accent_color": "#34d399",
        "flavor": "Coding, art, sound, marketing, and accounting all at 4 AM.",
    },
    "wishlist_goblin": {
        "key": "wishlist_goblin",
        "name": "Wishlist Goblin",
        "subtitle": "Bargain Stalker",
        "series": "Sqush Genesis Vol. 1",
        "rarity": "rare",
        "power": 220,
        "defense": 280,
        "icon": "bi-heart-fill",
        "bg_color": "#4a044e",
        "accent_color": "#f43f5e",
        "flavor": "Has 128 indie games bookmarked, waiting for that sweet notification.",
    },
    "patch_notes": {
        "key": "patch_notes",
        "name": "The 10-Page Patch Note",
        "subtitle": "Chronicler Scroll",
        "series": "Sqush Genesis Vol. 1",
        "rarity": "rare",
        "power": 240,
        "defense": 250,
        "icon": "bi-journal-code",
        "bg_color": "#172554",
        "accent_color": "#38bdf8",
        "flavor": "Fixed a 1-pixel gap in the pause menu and rewrote the entire engine.",
    },

    # Epic tier (12% pull chance)
    "quantum_debugger": {
        "key": "quantum_debugger",
        "name": "Quantum Debugger",
        "subtitle": "Time-Loop Fixer",
        "series": "Sqush Genesis Vol. 1",
        "rarity": "epic",
        "power": 450,
        "defense": 390,
        "icon": "bi-magic",
        "bg_color": "#3b0764",
        "accent_color": "#c084fc",
        "flavor": "Fixes null pointer exceptions before the code is even drafted.",
    },
    "floppy_artifact": {
        "key": "floppy_artifact",
        "name": "1.44MB Golden Floppy",
        "subtitle": "Ancient Relic",
        "series": "Sqush Genesis Vol. 1",
        "rarity": "epic",
        "power": 410,
        "defense": 460,
        "icon": "bi-floppy-fill",
        "bg_color": "#451a03",
        "accent_color": "#fbbf24",
        "flavor": "Contains the source code of a forgotten masterpiece from 1993.",
    },
    "speedrun_specter": {
        "key": "speedrun_specter",
        "name": "Speedrun Specter",
        "subtitle": "Boundary Breaker",
        "series": "Sqush Genesis Vol. 1",
        "rarity": "epic",
        "power": 480,
        "defense": 370,
        "icon": "bi-stopwatch-fill",
        "bg_color": "#022c22",
        "accent_color": "#2dd4bf",
        "flavor": "Cleared the entire 40-hour campaign in 3 minutes via backwards jump.",
    },

    # Legendary tier (3% pull chance)
    "sqush_whale": {
        "key": "sqush_whale",
        "name": "The Mythic Whale",
        "subtitle": "Apex Patron",
        "series": "Sqush Genesis Vol. 1",
        "rarity": "legendary",
        "power": 750,
        "defense": 700,
        "icon": "bi-gem",
        "bg_color": "#311042",
        "accent_color": "#facc15",
        "flavor": "Legends speak of a generous traveler whose tip jar drops shook the vault.",
    },
    "genesis_prime": {
        "key": "genesis_prime",
        "name": "Sqush Prime Sovereign",
        "subtitle": "Cosmic Indie Overlord",
        "series": "Sqush Genesis Vol. 1",
        "rarity": "legendary",
        "power": 999,
        "defense": 999,
        "icon": "bi-stars",
        "bg_color": "#111827",
        "accent_color": "#ff0055",
        "flavor": "The primordial spirit of independent creativity. Maximum comic clout.",
    },
}

# drop probabilities (:
RARITY_WEIGHTS = [
    ("common", 60),
    ("rare", 25),
    ("epic", 12),
    ("legendary", 3),
]

# recipes for crafting badges from duplicates (:
CRAFTING_RECIPES = {
    "comic_crafter": {
        "key": "comic_crafter",
        "name": "Comic Card Crafter Badge",
        "description": "Recycle 3 duplicate cards of any rarity to forge this badge.",
        "reward_badge_key": "comic_crafter",
        "required_count": 3,
        "required_rarity": "any",
        "icon": "bi-hammer",
        "color": "#ff9f1c",
    },
    "holo_hero": {
        "key": "holo_hero",
        "name": "Holo Hero Badge",
        "description": "Recycle 2 Rare duplicate cards into the holographic hero emblem.",
        "reward_badge_key": "holo_hero",
        "required_count": 2,
        "required_rarity": "rare",
        "icon": "bi-shield-shaded",
        "color": "#3aa0ff",
    },
    "comic_alchemist": {
        "key": "comic_alchemist",
        "name": "Comic Alchemist Badge",
        "description": "Transmute 2 Epic or Legendary duplicate cards into master alchemist prestige.",
        "reward_badge_key": "comic_alchemist",
        "required_count": 2,
        "required_rarity": "epic_or_legendary",
        "icon": "bi-magic",
        "color": "#9b51e0",
    },
}


def get_card_definition(card_key: str):
    return CARD_DEFINITIONS.get(card_key)


def get_all_card_definitions():
    return CARD_DEFINITIONS


def roll_random_card():
    # roll for rarity tier first
    rarities, weights = zip(*RARITY_WEIGHTS)
    chosen_rarity = random.choices(rarities, weights=weights, k=1)[0]

    # grab all matching cards
    pool = [k for k, v in CARD_DEFINITIONS.items() if v["rarity"] == chosen_rarity]
    if not pool:
        pool = list(CARD_DEFINITIONS.keys())

    chosen_key = random.choice(pool)
    return CARD_DEFINITIONS[chosen_key]


def award_card_to_user(user_id: int, source: str = "purchase", card_key: str = None) -> dict:
    # hands out a card drop to a user (:
    if not user_id:
        return None

    user = db.session.get(User, user_id)
    if not user:
        return None

    if card_key and card_key in CARD_DEFINITIONS:
        card = CARD_DEFINITIONS[card_key]
    else:
        card = roll_random_card()

    existing = UserCard.query.filter_by(user_id=user.id, card_key=card["key"]).first()
    is_duplicate = False

    if existing:
        existing.quantity += 1
        existing.updated_at = datetime.now(timezone.utc)
        is_duplicate = True
        total_quantity = existing.quantity
    else:
        new_card = UserCard(
            user_id=user.id,
            card_key=card["key"],
            quantity=1,
            obtained_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.session.add(new_card)
        total_quantity = 1

    # bell ring in notifications (:
    source_label = "purchase" if source == "purchase" else "game review"
    notif = Notification(
        user_id=user.id,
        message=f"[LOOT DROP] You pulled {card['name']} ({card['rarity'].title()}) from your {source_label}!",
        type="card_drop",
    )
    db.session.add(notif)
    db.session.commit()

    return {
        "card": card,
        "is_duplicate": is_duplicate,
        "quantity": total_quantity,
        "source": source,
    }


def get_user_inventory(user_id: int) -> list:
    # grab all user cards and pack them nicely with metadata
    if not user_id:
        return []

    rows = UserCard.query.filter_by(user_id=user_id).all()
    inventory = []

    for row in rows:
        defn = get_card_definition(row.card_key)
        if not defn:
            continue
        item = dict(defn)
        item["quantity"] = row.quantity
        item["is_duplicate"] = row.quantity > 1
        item["duplicate_count"] = max(0, row.quantity - 1)
        item["obtained_at"] = row.obtained_at
        item["updated_at"] = row.updated_at
        inventory.append(item)

    # sort by rarity priority then name
    rarity_order = {"legendary": 4, "epic": 3, "rare": 2, "common": 1}
    inventory.sort(key=lambda x: (rarity_order.get(x["rarity"], 0), x["name"]), reverse=True)
    return inventory


def get_user_duplicates(user_id: int) -> list:
    # only returns cards where quantity > 1 so user can trade or craft
    full_inv = get_user_inventory(user_id)
    return [c for c in full_inv if c["quantity"] > 1]


def get_crafting_recipes_status(user_id: int) -> list:
    # returns recipes with user progress info
    duplicates = get_user_duplicates(user_id)
    user = db.session.get(User, user_id) if user_id else None

    # count duplicates by rarity
    common_dupes = sum(c["duplicate_count"] for c in duplicates if c["rarity"] == "common")
    rare_dupes = sum(c["duplicate_count"] for c in duplicates if c["rarity"] == "rare")
    epic_dupes = sum(c["duplicate_count"] for c in duplicates if c["rarity"] == "epic")
    legendary_dupes = sum(c["duplicate_count"] for c in duplicates if c["rarity"] == "legendary")
    any_dupes = sum(c["duplicate_count"] for c in duplicates)
    epic_or_legendary_dupes = epic_dupes + legendary_dupes

    results = []
    for key, recipe in CRAFTING_RECIPES.items():
        r = dict(recipe)
        req_rarity = r["required_rarity"]
        req_count = r["required_count"]

        if req_rarity == "rare":
            available = rare_dupes
        elif req_rarity == "epic_or_legendary":
            available = epic_or_legendary_dupes
        else:
            available = any_dupes

        badge_defn = get_badge_definition(r["reward_badge_key"])
        r["badge_name"] = badge_defn["name"] if badge_defn else r["name"]
        r["available_dupes"] = available
        r["can_craft"] = available >= req_count
        r["already_unlocked"] = False
        if user:
            from models.user import UserBadge
            r["already_unlocked"] = UserBadge.query.filter_by(
                user_id=user.id, badge_key=r["reward_badge_key"]
            ).first() is not None

        results.append(r)
    return results


def execute_craft(user_id: int, recipe_key: str) -> tuple[bool, str]:
    # melts down duplicate cards to forge a shiny badge (:
    user = db.session.get(User, user_id)
    if not user:
        return False, "User not found."

    recipe = CRAFTING_RECIPES.get(recipe_key)
    if not recipe:
        return False, "Recipe does not exist."

    # check which duplicates to consume
    dupe_rows = UserCard.query.filter(UserCard.user_id == user.id, UserCard.quantity > 1).all()
    req_rarity = recipe["required_rarity"]
    req_count = recipe["required_count"]

    eligible_rows = []
    for row in dupe_rows:
        defn = get_card_definition(row.card_key)
        if not defn:
            continue
        card_rarity = defn.get("rarity")
        if req_rarity == "rare" and card_rarity != "rare":
            continue
        if req_rarity == "epic_or_legendary" and card_rarity not in ["epic", "legendary"]:
            continue
        eligible_rows.append(row)

    total_available = sum(r.quantity - 1 for r in eligible_rows)
    if total_available < req_count:
        return False, f"Not enough duplicates. You need {req_count}, but have {total_available}."

    # deduct duplicates
    needed = req_count
    for row in eligible_rows:
        removable = row.quantity - 1
        to_take = min(removable, needed)
        row.quantity -= to_take
        row.updated_at = datetime.now(timezone.utc)
        needed -= to_take
        if needed <= 0:
            break

    # grant badge (:
    badge_key = recipe["reward_badge_key"]
    granted = grant_manual_badge(user, badge_key, notify=True)

    db.session.commit()
    return True, f"Successfully crafted {recipe['name']}!"


def propose_trade(sender_id: int, receiver_id: int, offered_card_key: str, requested_card_key: str = None, note: str = None) -> tuple[bool, str, CardTrade]:
    # sender offers a duplicate card to a homie (:
    if sender_id == receiver_id:
        return False, "You cannot trade cards with yourself (: Talk to a homie!", None

    sender = db.session.get(User, sender_id)
    receiver = db.session.get(User, receiver_id)
    if not sender or not receiver:
        return False, "User not found.", None

    # sender MUST have at least 2 copies of the offered card!
    sender_card = UserCard.query.filter_by(user_id=sender_id, card_key=offered_card_key).first()
    if not sender_card or sender_card.quantity < 2:
        return False, "You can only trade duplicate cards you have at least 2 copies of (: Keep your collection complete!", None

    offered_def = get_card_definition(offered_card_key)
    if not offered_def:
        return False, "Invalid card offered.", None

    requested_def = get_card_definition(requested_card_key) if requested_card_key else None

    trade = CardTrade(
        sender_id=sender_id,
        receiver_id=receiver_id,
        offered_card_key=offered_card_key,
        requested_card_key=requested_card_key,
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(trade)
    db.session.flush()

    # create dm thread message linking the trade (:
    trade_text = f"[CARD TRADE OFFER] Offered: {offered_def['name']}"
    if requested_def:
        trade_text += f" | Requested: {requested_def['name']}"
    else:
        trade_text += " | Homie Gift (No card requested)"
    if note:
        trade_text += f"\nNote: {note}"

    msg = DirectMessage(
        sender_id=sender_id,
        recipient_id=receiver_id,
        content=trade_text,
        trade_id=trade.id,
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(msg)

    # notify receiver (:
    notif = Notification(
        user_id=receiver_id,
        message=f"{sender.username} offered you a card trade in DMs: {offered_def['name']}!",
        type="card_trade",
    )
    db.session.add(notif)
    db.session.commit()

    return True, "Trade offer sent to your homie!", trade


def execute_trade_action(trade_id: int, actor_id: int, action: str) -> tuple[bool, str]:
    # accept, decline or cancel a trade (:
    trade = db.session.get(CardTrade, trade_id)
    if not trade:
        return False, "Trade not found."

    if trade.status != "pending":
        return False, f"Trade is already {trade.status}."

    if action == "cancel":
        if trade.sender_id != actor_id:
            return False, "Only the sender can cancel their offer."
        trade.status = "cancelled"
        trade.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        return True, "Trade offer cancelled."

    if action == "decline":
        if trade.receiver_id != actor_id:
            return False, "Only the recipient can decline this trade."
        trade.status = "declined"
        trade.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        return True, "Trade declined."

    if action == "accept":
        if trade.receiver_id != actor_id:
            return False, "Only the recipient can accept this trade."

        # verify sender still has at least 1 copy of offered card
        sender_card = UserCard.query.filter_by(user_id=trade.sender_id, card_key=trade.offered_card_key).first()
        if not sender_card or sender_card.quantity < 1:
            trade.status = "cancelled"
            trade.completed_at = datetime.now(timezone.utc)
            db.session.commit()
            return False, "The sender no longer owns this card. Trade cancelled."

        # if a requested card was specified, verify receiver owns at least 1 copy
        receiver_requested_card = None
        if trade.requested_card_key:
            receiver_requested_card = UserCard.query.filter_by(
                user_id=trade.receiver_id, card_key=trade.requested_card_key
            ).first()
            if not receiver_requested_card or receiver_requested_card.quantity < 1:
                return False, "You do not own the card requested for this trade."

        # execute atomic card swap (:
        # 1. Deduct offered card from sender
        sender_card.quantity -= 1
        sender_card.updated_at = datetime.now(timezone.utc)

        # 2. Add offered card to receiver
        rec_card = UserCard.query.filter_by(user_id=trade.receiver_id, card_key=trade.offered_card_key).first()
        if rec_card:
            rec_card.quantity += 1
            rec_card.updated_at = datetime.now(timezone.utc)
        else:
            rec_card = UserCard(
                user_id=trade.receiver_id,
                card_key=trade.offered_card_key,
                quantity=1,
                obtained_at=datetime.now(timezone.utc),
            )
            db.session.add(rec_card)

        # 3. Swap requested card if specified
        if trade.requested_card_key and receiver_requested_card:
            receiver_requested_card.quantity -= 1
            receiver_requested_card.updated_at = datetime.now(timezone.utc)

            sender_req_card = UserCard.query.filter_by(
                user_id=trade.sender_id, card_key=trade.requested_card_key
            ).first()
            if sender_req_card:
                sender_req_card.quantity += 1
                sender_req_card.updated_at = datetime.now(timezone.utc)
            else:
                sender_req_card = UserCard(
                    user_id=trade.sender_id,
                    card_key=trade.requested_card_key,
                    quantity=1,
                    obtained_at=datetime.now(timezone.utc),
                )
                db.session.add(sender_req_card)

        trade.status = "accepted"
        trade.completed_at = datetime.now(timezone.utc)

        # award homie trader badge to both users (:
        grant_manual_badge(trade.sender, "comic_trader", notify=True)
        grant_manual_badge(trade.receiver, "comic_trader", notify=True)

        # notifications
        offered_def = get_card_definition(trade.offered_card_key)
        offered_name = offered_def["name"] if offered_def else trade.offered_card_key
        notif_sender = Notification(
            user_id=trade.sender_id,
            message=f"{trade.receiver.username} accepted your card trade for {offered_name}!",
            type="card_trade",
        )
        notif_rec = Notification(
            user_id=trade.receiver_id,
            message=f"Trade complete! You received {offered_name} from {trade.sender.username}!",
            type="card_drop",
        )
        db.session.add(notif_sender)
        db.session.add(notif_rec)

        db.session.commit()
        return True, "Trade completed successfully!"

    return False, "Unknown action."

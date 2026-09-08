from datetime import datetime, timezone
from extensions import db
from models.user import User, UserBadge, Notification, Friendship
from models.commerce import Purchase, Gift, Tip
from models.game import Review


BADGE_DEFINITIONS = {
    "day_one": {
        "key": "day_one",
        "name": "Day One",
        "description": "Joined sqush during the early launch era",
        "icon": "bi-stars",
        "color": "#ffe14d",
        "category": "veteran",
        "tier": "legendary",
        "condition": lambda u: (u.id <= 100) or (u.created_at and u.created_at.year <= 2026),
    },
    "big_spender": {
        "key": "big_spender",
        "name": "Big Spender",
        "description": "Spent at least 25.00€ supporting indie developers",
        "icon": "bi-cash-coin",
        "color": "#33d17a",
        "category": "spending",
        "tier": "gold",
        "condition": lambda u: (
            sum((p.price_paid or 0.0) for p in Purchase.query.filter_by(user_id=u.id, refunded=False).all())
            + sum((t.amount or 0.0) for t in Tip.query.filter_by(user_id=u.id).all())
        ) >= 25.0,
    },
    "whale": {
        "key": "whale",
        "name": "Sqush Whale",
        "description": "Spent 100.00€+ supporting creators on sqush",
        "icon": "bi-gem",
        "color": "#9b51e0",
        "category": "spending",
        "tier": "diamond",
        "condition": lambda u: (
            sum((p.price_paid or 0.0) for p in Purchase.query.filter_by(user_id=u.id, refunded=False).all())
            + sum((t.amount or 0.0) for t in Tip.query.filter_by(user_id=u.id).all())
        ) >= 100.0,
    },
    "patron": {
        "key": "patron",
        "name": "Tip Jar Hero",
        "description": "Donated to an indie developer through their game's Tip Jar",
        "icon": "bi-cup-hot-fill",
        "color": "#ffe14d",
        "category": "social",
        "tier": "bronze",
        "condition": lambda u: Tip.query.filter_by(user_id=u.id).count() >= 1,
    },
    "game_dev": {
        "key": "game_dev",
        "name": "Game Dev",
        "description": "Published at least one game on sqush",
        "icon": "bi-controller",
        "color": "#3aa0ff",
        "category": "creator",
        "tier": "gold",
        "condition": lambda u: (u.role == "dev") or (len(u.games) > 0),
    },
    "collector": {
        "key": "collector",
        "name": "Collector",
        "description": "Owns 5 or more games in their library",
        "icon": "bi-collection-fill",
        "color": "#ff9f1c",
        "category": "collection",
        "tier": "silver",
        "condition": lambda u: Purchase.query.filter_by(user_id=u.id, refunded=False).count() >= 5,
    },
    "generous": {
        "key": "generous",
        "name": "Generous Soul",
        "description": "Gifted a game to another sqush player",
        "icon": "bi-gift-fill",
        "color": "#ff3b30",
        "category": "social",
        "tier": "gold",
        "condition": lambda u: Gift.query.filter_by(sender_id=u.id).count() >= 1,
    },
    "socialite": {
        "key": "socialite",
        "name": "Social Butterfly",
        "description": "Connected with 5 or more accepted friends",
        "icon": "bi-people-fill",
        "color": "#ff69b4",
        "category": "social",
        "tier": "silver",
        "condition": lambda u: Friendship.query.filter(
            ((Friendship.sender_id == u.id) | (Friendship.receiver_id == u.id)),
            Friendship.status == "accepted"
        ).count() >= 5,
    },
    "critic": {
        "key": "critic",
        "name": "Top Critic",
        "description": "Wrote 3 or more helpful game reviews",
        "icon": "bi-chat-quote-fill",
        "color": "#00c4cc",
        "category": "community",
        "tier": "silver",
        "condition": lambda u: Review.query.filter_by(user_id=u.id).count() >= 3,
    },
    "hacker": {
        "key": "hacker",
        "name": "Hack Clubber",
        "description": "Verified Hack Club community member",
        "icon": "bi-terminal-fill",
        "color": "#ec3750",
        "category": "special",
        "tier": "special",
        "condition": lambda u: bool(u.hackclub_id),
    },
    "verified": {
        "key": "verified",
        "name": "Verified Account",
        "description": "Confirmed their email address",
        "icon": "bi-patch-check-fill",
        "color": "#3aa0ff",
        "category": "account",
        "tier": "bronze",
        "condition": lambda u: bool(u.email_verified),
    },
}

TIER_PRIORITY = {
    "legendary": 100,
    "diamond": 90,
    "gold": 70,
    "special": 60,
    "silver": 50,
    "bronze": 30,
}


def get_badge_definition(badge_key: str):
    """Retrieve static metadata for a badge key."""
    defn = BADGE_DEFINITIONS.get(badge_key)
    if defn:
        return {k: v for k, v in defn.items() if k != "condition"}
    return None


def get_all_badges():
    # returns all of the badges metadata
    return {k: get_badge_definition(k) for k in BADGE_DEFINITIONS}


def evaluate_eligible_badges(user: User) -> set:
    # evaluetes conditions for all badges against the users
    eligible = set()
    if not user:
        return eligible

    for key, defn in BADGE_DEFINITIONS.items():
        cond = defn.get("condition")
        if cond:
            try:
                if cond(user):
                    eligible.add(key)
            except Exception as e:
                print(f"DEBUG: Error evaluating badge '{key}' for user {user.id}: {e}")
    return eligible


def sync_user_badges(user: User, notify: bool = True) -> list:
    # Evaluetes eligible badgesand persist new UserBadge rows.
    #sends in  app notifications for unlocked badges and returns the list of newly unlocked badges. enough talking its much
    if not user or not user.id:
        return []

    eligible_keys = evaluate_eligible_badges(user)
    existing_rows = UserBadge.query.filter_by(user_id=user.id).all()
    existing_keys = {ub.badge_key for ub in existing_rows}

    newly_unlocked = []
    has_changes = False

    for key in eligible_keys:
        if key not in existing_keys:
            defn = get_badge_definition(key)
            if defn:
                ub = UserBadge(
                    user_id=user.id,
                    badge_key=key,
                    unlocked_at=datetime.now(timezone.utc),
                )
                db.session.add(ub)
                has_changes = True
                newly_unlocked.append(defn)

                if notify:
                    notif = Notification(
                        user_id=user.id,
                        message=f" Badge unlocked: {defn['name']}! ({defn['description']})",
                        type="badge_unlocked",
                    )
                    db.session.add(notif)

    if has_changes:
        db.session.commit()

    return newly_unlocked


def get_user_badges(user: User) -> list:
    # returns a list of all unlocked badge metadata for the user. orders by tier priority and unlocked date.
    if not user or not user.id:
        return []

    user_badge_rows = UserBadge.query.filter_by(user_id=user.id).all()
    results = []

    for row in user_badge_rows:
        defn = get_badge_definition(row.badge_key)
        if not defn:
            defn = {
                "key": row.badge_key,
                "name": row.badge_key.replace("_", " ").title(),
                "description": "Special achievement",
                "icon": "bi-award-fill",
                "color": "#ffe14d",
                "category": "special",
                "tier": "bronze",
            }

        badge_item = dict(defn)
        badge_item["unlocked"] = True
        badge_item["unlocked_at"] = row.unlocked_at
        badge_item["is_featured"] = (user.featured_badge_key == row.badge_key)
        badge_item["priority"] = TIER_PRIORITY.get(defn.get("tier"), 10)
        results.append(badge_item)

    #  featured first, then highest priority tier, then unlock date description
    results.sort(
        key=lambda b: (
            1 if b["is_featured"] else 0,
            b["priority"],
            b["unlocked_at"] or datetime.min,
        ),
        reverse=True,
    )
    return results


def get_featured_badge(user: User):
    if not user or not user.id:
        return None

    if user.featured_badge_key:
        defn = get_badge_definition(user.featured_badge_key)
        if defn:
            badge_item = dict(defn)
            badge_item["unlocked"] = True
            badge_item["is_featured"] = True
            badge_item["priority"] = TIER_PRIORITY.get(defn.get("tier"), 10)
            return badge_item

    unlocked_badges = get_user_badges(user)
    return unlocked_badges[0] if unlocked_badges else None


def set_featured_badge(user: User, badge_key: str) -> bool:
    # sets or unsets the featured badge for a user.
    # passing empty the currently featured key will toggle it.
    if not user or not user.id:
        return False

    if not badge_key or badge_key == "none":
        user.featured_badge_key = None
        db.session.commit()
        return True

    # make sure they actually earned it first (:
    has_badge = UserBadge.query.filter_by(user_id=user.id, badge_key=badge_key).first()
    if not has_badge:
        return False

    if user.featured_badge_key == badge_key:
        # toggle it off (:
        user.featured_badge_key = None
    else:
        user.featured_badge_key = badge_key

    db.session.commit()
    return True


def grant_manual_badge(user: User, badge_key: str, notify: bool = True) -> bool:
    # manually grants a badge to a user.
    if not user or not user.id:
        return False

    existing = UserBadge.query.filter_by(user_id=user.id, badge_key=badge_key).first()
    if existing:
        return True

    defn = get_badge_definition(badge_key)
    badge_name = defn["name"] if defn else badge_key

    ub = UserBadge(
        user_id=user.id,
        badge_key=badge_key,
        unlocked_at=datetime.now(timezone.utc),
    )
    db.session.add(ub)

    if notify:
        notif = Notification(
            user_id=user.id,
            message=f" Special badge granted: {badge_name}!",
            type="badge_unlocked",
        )
        db.session.add(notif)

    db.session.commit()
    return True

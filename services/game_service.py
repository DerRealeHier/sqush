from datetime import datetime, timezone
from sqlalchemy import func as _sqlfunc
from extensions import db
from models.game import Game, GameStats
from models.commerce import Purchase, Wishlist, Tip


def calculate_game_revenue(game):
    # let sql do the heavy lifting instead of loading everything into python xD
    # ignore weird old rows with null prices (:
    result = db.session.query(_sqlfunc.sum(Purchase.price_paid)).filter(
        Purchase.game_id == game.id,
        Purchase.refunded == False,
        Purchase.price_paid != None,
    ).scalar()
    return result or 0.0


def calculate_game_tips(game):
    # sum up all the tips. developers need their coffee (:
    result = db.session.query(_sqlfunc.sum(Tip.amount)).filter(
        Tip.game_id == game.id,
    ).scalar()
    return result or 0.0



def calculate_display_price(game):
    #I had this in like all functions. Now I have an own one for it.
    if game.is_on_sale and game.discount_percent > 0:
        return game.price * (1 - game.discount_percent / 100)
    return game.price


#dont wanna end up with doing this several times over the code base
#also we take the length of the review into account. It does not change it that much but you understand?
def calculate_review_score(review):
    text_len = len(review.comment or "")
    length_factor = min(text_len / 200, 1.0)  # ab 200 Zeichen voller Bonus
    return (review.helpful_count * 2) + (review.funny_count * 1) + (length_factor * 3)


def _get_tag_set(game):
    # small helper so we don't repeat all again and again.
    if not game.tags:
        return set()
    return {t.strip().lower() for t in game.tags.split(",") if t.strip()}


def get_popular_games(exclude_ids=None, limit=6):
    # let the db sort it so our ram doesn't explode lol
    exclude_ids = exclude_ids or set()
    query = (
        db.session.query(Game)
        .outerjoin(Purchase, (Purchase.game_id == Game.id) & (Purchase.refunded == False))
        .group_by(Game.id)
        .order_by(_sqlfunc.count(Purchase.id).desc())
    )
    if exclude_ids:
        query = query.filter(~Game.id.in_(exclude_ids))
    return query.limit(limit).all()


_rec_cache = {}
_REC_CACHE_TTL = 60  # seconds


def get_recommended_games(user, limit=6):
    if not user.is_authenticated:
        return []

    # check cache first so we don't spam the db (:
    now_ts = datetime.now(timezone.utc).timestamp()
    cached = _rec_cache.get(user.id)
    if cached and (now_ts - cached["time"] < _REC_CACHE_TTL):
        cached_ids = cached["ids"][:limit]
        if cached_ids:
            games_by_id = {g.id: g for g in Game.query.filter(Game.id.in_(cached_ids)).all()}
            return [games_by_id[gid] for gid in cached_ids if gid in games_by_id]

    my_owned_ids = {
        row[0]
        for row in db.session.query(Purchase.game_id)
        .filter_by(user_id=user.id, refunded=False)
        .all()
    }

    if not my_owned_ids:
        # new baby account, just show them the hits (:
        return get_popular_games(exclude_ids=set(), limit=limit)

    all_games = Game.query.all()
    games_by_id = {g.id: g for g in all_games}

    # see what kind of games they like (:
    my_tags = set()
    for gid in my_owned_ids:
        game = games_by_id.get(gid)
        if game:
            my_tags |= _get_tag_set(game)

    # grab raw ids so it's super snappy
    all_purchases = db.session.query(Purchase.game_id, Purchase.user_id).filter_by(refunded=False).all()
    owners_by_game = {}
    games_by_user = {}
    for game_id, user_id in all_purchases:
        owners_by_game.setdefault(game_id, set()).add(user_id)
        games_by_user.setdefault(user_id, set()).add(game_id)

    # find people with the same taste (:
    tag_similar_user_ids = set()
    if my_tags:
        for uid, gids in games_by_user.items():
            if uid == user.id:
                continue
            for gid in gids:
                owned_game = games_by_id.get(gid)
                if owned_game and (_get_tag_set(owned_game) & my_tags):
                    tag_similar_user_ids.add(uid)
                    break

    # who else plays the same stuff as me?
    similar_library_user_ids = {
        uid for uid, gids in games_by_user.items()
        if uid != user.id and (gids & my_owned_ids)
    }

    wishlisters_by_game = {}
    for game_id, user_id in db.session.query(Wishlist.game_id, Wishlist.user_id).all():
        wishlisters_by_game.setdefault(game_id, set()).add(user_id)

    scores = {}
    for game in all_games:
        if game.id in my_owned_ids:
            continue

        owners = owners_by_game.get(game.id, set())
        wishlisters = wishlisters_by_game.get(game.id, set())

        tag_score = len(owners & tag_similar_user_ids)
        popularity_score = len(owners)
        similar_wishlist_score = len(wishlisters & similar_library_user_ids)

        total_score = (tag_score * 3) + (similar_wishlist_score * 2) + (popularity_score * 1)
        if total_score > 0:
            scores[game.id] = total_score

    if not scores:
        return get_popular_games(exclude_ids=my_owned_ids, limit=limit)

    top_ids = sorted(scores, key=lambda gid: scores[gid], reverse=True)[:limit]
    _rec_cache[user.id] = {"time": now_ts, "ids": top_ids}
    return [games_by_id[gid] for gid in top_ids]


def update_daily_stats(game):
    # one row per day.
    today = datetime.now(timezone.utc).date()
    entry = GameStats.query.filter_by(game_id=game.id, date=today).first()

    wishlist_count = Wishlist.query.filter_by(game_id=game.id).count()
    purchase_count = Purchase.query.filter_by(game_id=game.id).count()
    revenue = calculate_game_revenue(game)

    if entry:
        entry.views = game.view_count
        entry.wishlist_count = wishlist_count
        entry.purchase_count = purchase_count
        entry.revenue = revenue
    else:
        entry = GameStats(
            game_id=game.id,
            date=today,
            views=game.view_count,
            wishlist_count=wishlist_count,
            purchase_count=purchase_count,
            revenue=revenue
        )
        db.session.add(entry)

    db.session.commit()


_last_sale_check: "datetime | None" = None


def check_sales_expiry():
    global _last_sale_check
    now = datetime.now(timezone.utc)
    # check at most once a minute, no need to hammer the db on every reload xD
    if _last_sale_check is not None and (now - _last_sale_check).total_seconds() < 60:
        return
    _last_sale_check = now

    # only get active sales.
    sales_to_check = Game.query.filter(Game.is_on_sale == True, Game.sale_end_date != None).all()
    changed = False

    for game in sales_to_check:
        db_date = game.sale_end_date
        if db_date.tzinfo is None:
            db_date = db_date.replace(tzinfo=timezone.utc)
        if db_date < now:
            game.is_on_sale = False
            game.discount_percent = 0
            game.sale_end_date = None
            changed = True
            print(f"DEBUG: Sale for {game.title} expired.")

    if changed:
        db.session.commit()

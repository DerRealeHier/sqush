from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import current_user, login_required
from sqlalchemy import or_
from extensions import db
from models.card import CardTrade
from services.card_service import (
    get_all_card_definitions,
    get_user_inventory,
    get_user_duplicates,
    get_crafting_recipes_status,
    execute_craft,
    get_card_definition,
    award_card_to_user,
)

inventory_bp = Blueprint("inventory", __name__)


# cards, binder and crafting hub (:
@inventory_bp.route("/inventory")
@login_required
def index():
    tab = request.args.get("tab", "binder")
    all_cards = get_all_card_definitions()
    user_cards = get_user_inventory(current_user.id)

    # organize by key for quick lookup
    owned_map = {c["key"]: c for c in user_cards}

    #  includes unowned cards so users see what is missing (:
    binder = []
    for key, defn in all_cards.items():
        card_item = dict(defn)
        if key in owned_map:
            card_item["owned"] = True
            card_item["quantity"] = owned_map[key]["quantity"]
            card_item["is_duplicate"] = owned_map[key]["is_duplicate"]
            card_item["duplicate_count"] = owned_map[key]["duplicate_count"]
            card_item["obtained_at"] = owned_map[key]["obtained_at"]
        else:
            card_item["owned"] = False
            card_item["quantity"] = 0
            card_item["is_duplicate"] = False
            card_item["duplicate_count"] = 0
            card_item["obtained_at"] = None
        binder.append(card_item)

    # owned first, then rarity, then name
    rarity_order = {"legendary": 4, "epic": 3, "rare": 2, "common": 1}
    binder.sort(key=lambda x: (1 if x["owned"] else 0, rarity_order.get(x["rarity"], 0), x["name"]), reverse=True)

    unique_owned = len(user_cards)
    total_catalog = len(all_cards)
    completion_pct = int((unique_owned / total_catalog) * 100) if total_catalog else 0
    total_duplicates = sum(c["duplicate_count"] for c in user_cards)

    # crafting recipes info
    recipes = get_crafting_recipes_status(current_user.id)

    # trade history with homies (:
    trades = CardTrade.query.filter(
        or_(CardTrade.sender_id == current_user.id, CardTrade.receiver_id == current_user.id)
    ).order_by(CardTrade.created_at.desc()).limit(20).all()

    # enrich trades with card definitions
    trade_items = []
    for t in trades:
        item = {
            "trade": t,
            "offered_card": get_card_definition(t.offered_card_key),
            "requested_card": get_card_definition(t.requested_card_key) if t.requested_card_key else None,
            "is_sender": t.sender_id == current_user.id,
            "other_user": t.receiver if t.sender_id == current_user.id else t.sender,
        }
        trade_items.append(item)

    # check if user just got a loot drop from session (:
    recent_drop = session.pop("recent_loot_drop", None)

    return render_template(
        "inventory.html",
        binder=binder,
        user_cards=user_cards,
        unique_owned=unique_owned,
        total_catalog=total_catalog,
        completion_pct=completion_pct,
        total_duplicates=total_duplicates,
        recipes=recipes,
        trade_items=trade_items,
        tab=tab,
        recent_drop=recent_drop,
    )


# melting duplicates into badges (:
@inventory_bp.route("/inventory/craft/<recipe_key>", methods=["POST"])
@login_required
def craft(recipe_key):
    success, msg = execute_craft(current_user.id, recipe_key)
    if success:
        flash(f"[FORGED] {msg}", "success")
    else:
        flash(f"[CRAFT FAILED] {msg}", "error")
    return redirect(url_for("inventory.index", tab="crafting"))


# handy json endpoint so the dm trade modal can fetch duplicate cards (:
@inventory_bp.route("/api/inventory/my-duplicates")
@login_required
def my_duplicates():
    dupes = get_user_duplicates(current_user.id)
    return jsonify({"duplicates": dupes})


# quick dev pull to test the drop feel (:
@inventory_bp.route("/inventory/test-drop", methods=["POST"])
@login_required
def test_drop():
    drop = award_card_to_user(current_user.id, source="test pull")
    session["recent_loot_drop"] = drop
    flash(f"[TEST LOOT] Pulled {drop['card']['name']} ({drop['card']['rarity'].title()})!", "info")
    return redirect(url_for("inventory.index"))

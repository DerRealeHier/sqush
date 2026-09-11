import unittest
from app import create_app
from extensions import db
from models.user import User, UserBadge, Notification
from models.game import Game, Review
from models.card import UserCard, CardTrade
from models.message import DirectMessage
from services.card_service import (
    CARD_DEFINITIONS,
    award_card_to_user,
    get_user_inventory,
    get_user_duplicates,
    propose_trade,
    execute_trade_action,
    execute_craft,
    get_crafting_recipes_status,
)


class CardsInventoryTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
            "SECRET_KEY": "test_secret_key",
        })
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

            # User 1: Player Alice
            self.alice = User(
                username="alice",
                email="alice@sqush.dev",
                role="user",
                email_verified=True,
                two_fa_enabled=False,
            )
            self.alice.set_password("AlicePassword123!")
            db.session.add(self.alice)

            # User 2: Player Bob
            self.bob = User(
                username="bob",
                email="bob@sqush.dev",
                role="user",
                email_verified=True,
                two_fa_enabled=False,
            )
            self.bob.set_password("BobPassword123!")
            db.session.add(self.bob)

            # Developer Dave
            self.dave = User(
                username="dave",
                email="dave@sqush.dev",
                role="dev",
                email_verified=True,
                two_fa_enabled=False,
            )
            self.dave.set_password("DavePassword123!")
            db.session.add(self.dave)

            db.session.commit()

            # Game published by Dave
            self.game = Game(
                title="Pixel Brawler",
                genre="Action",
                price=5.0,
                download_path="uploads/fake.zip",
                developer_id=self.dave.id,
            )
            db.session.add(self.game)
            db.session.commit()

            self.alice_id = self.alice.id
            self.bob_id = self.bob.id
            self.dave_id = self.dave.id
            self.game_id = self.game.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def login(self, username, password):
        return self.client.post("/login", data={
            "username": username,
            "password": password
        }, follow_redirects=True)

    def test_award_card_and_duplicate_tracking(self):
        # pulling cards and tracking quantities (:
        with self.app.app_context():
            # First pull of squshy_slime
            res1 = award_card_to_user(self.alice_id, source="purchase", card_key="squshy_slime")
            self.assertIsNotNone(res1)
            self.assertFalse(res1["is_duplicate"])
            self.assertEqual(res1["quantity"], 1)

            card_row = UserCard.query.filter_by(user_id=self.alice_id, card_key="squshy_slime").first()
            self.assertIsNotNone(card_row)
            self.assertEqual(card_row.quantity, 1)

            # Second pull of same card -> duplicate!
            res2 = award_card_to_user(self.alice_id, source="purchase", card_key="squshy_slime")
            self.assertTrue(res2["is_duplicate"])
            self.assertEqual(res2["quantity"], 2)

            card_row_updated = UserCard.query.filter_by(user_id=self.alice_id, card_key="squshy_slime").first()
            self.assertEqual(card_row_updated.quantity, 2)

            # Check inventory and duplicates helpers
            inv = get_user_inventory(self.alice_id)
            self.assertEqual(len(inv), 1)
            self.assertTrue(inv[0]["is_duplicate"])
            self.assertEqual(inv[0]["duplicate_count"], 1)

            dupes = get_user_duplicates(self.alice_id)
            self.assertEqual(len(dupes), 1)
            self.assertEqual(dupes[0]["key"], "squshy_slime")

    def test_loot_drop_on_first_review_only(self):
        # review drops loot, but editing review does not (:
        self.login("alice", "AlicePassword123!")

        # Post first review
        res = self.client.post(f"/rate_game/{self.game_id}", data={
            "rating": "1",
            "comment": "Super cool comic game!",
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with self.app.app_context():
            alice_cards = UserCard.query.filter_by(user_id=self.alice_id).all()
            self.assertEqual(len(alice_cards), 1)
            card_key = alice_cards[0].card_key
            self.assertEqual(alice_cards[0].quantity, 1)

            # Notification created for drop
            notif = Notification.query.filter_by(user_id=self.alice_id, type="card_drop").first()
            self.assertIsNotNone(notif)
            self.assertIn("[LOOT DROP]", notif.message)

        # Update / edit existing review
        res2 = self.client.post(f"/rate_game/{self.game_id}", data={
            "rating": "1",
            "comment": "Updated comment, still cool!",
        }, follow_redirects=True)
        self.assertEqual(res2.status_code, 200)

        with self.app.app_context():
            # Should still only have 1 card, not another drop!
            alice_cards_after = UserCard.query.filter_by(user_id=self.alice_id).all()
            total_cards = sum(c.quantity for c in alice_cards_after)
            self.assertEqual(total_cards, 1)

    def test_trade_proposal_requires_duplicates(self):
        # Alice cannot trade a card she only owns 1 copy of (:
        with self.app.app_context():
            award_card_to_user(self.alice_id, card_key="squshy_slime")  # qty = 1

            # Proposing trade with only 1 copy must fail!
            success, msg, trade = propose_trade(
                sender_id=self.alice_id,
                receiver_id=self.bob_id,
                offered_card_key="squshy_slime",
                requested_card_key="pixel_paladin",
            )
            self.assertFalse(success)
            self.assertIn("duplicate", msg.lower())

            # Now give Alice a second copy -> qty = 2 (duplicate available!)
            award_card_to_user(self.alice_id, card_key="squshy_slime")

            success2, msg2, trade2 = propose_trade(
                sender_id=self.alice_id,
                receiver_id=self.bob_id,
                offered_card_key="squshy_slime",
                requested_card_key="pixel_paladin",
                note="Hey Bob, let's swap!",
            )
            self.assertTrue(success2)
            self.assertIsNotNone(trade2)
            self.assertEqual(trade2.status, "pending")

            # Check linked direct message
            dm = DirectMessage.query.filter_by(trade_id=trade2.id).first()
            self.assertIsNotNone(dm)
            self.assertIn("[CARD TRADE OFFER]", dm.content)

    def test_trade_acceptance_and_card_swap(self):
        # Alice offers squshy_slime for Bob's pixel_paladin (:
        with self.app.app_context():
            # Setup: Alice has 2x squshy_slime
            award_card_to_user(self.alice_id, card_key="squshy_slime")
            award_card_to_user(self.alice_id, card_key="squshy_slime")

            # Setup: Bob has 1x pixel_paladin
            award_card_to_user(self.bob_id, card_key="pixel_paladin")

            # Propose trade
            _, _, trade = propose_trade(
                sender_id=self.alice_id,
                receiver_id=self.bob_id,
                offered_card_key="squshy_slime",
                requested_card_key="pixel_paladin",
            )
            trade_id = trade.id

        # Bob logs in and accepts the trade
        self.login("bob", "BobPassword123!")
        res = self.client.post(f"/messages/trade/{trade_id}/accept", follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with self.app.app_context():
            # Check trade status
            trade_row = db.session.get(CardTrade, trade_id)
            self.assertEqual(trade_row.status, "accepted")

            # Check Alice cards: squshy_slime 2 -> 1, pixel_paladin 0 -> 1
            alice_slime = UserCard.query.filter_by(user_id=self.alice_id, card_key="squshy_slime").first()
            self.assertEqual(alice_slime.quantity, 1)
            alice_paladin = UserCard.query.filter_by(user_id=self.alice_id, card_key="pixel_paladin").first()
            self.assertEqual(alice_paladin.quantity, 1)

            # Check Bob cards: pixel_paladin 1 -> 0, squshy_slime 0 -> 1
            bob_paladin = UserCard.query.filter_by(user_id=self.bob_id, card_key="pixel_paladin").first()
            self.assertEqual(bob_paladin.quantity, 0)
            bob_slime = UserCard.query.filter_by(user_id=self.bob_id, card_key="squshy_slime").first()
            self.assertEqual(bob_slime.quantity, 1)

            # Homie Trader badge awarded to both Alice and Bob (:
            alice_badge = UserBadge.query.filter_by(user_id=self.alice_id, badge_key="comic_trader").first()
            bob_badge = UserBadge.query.filter_by(user_id=self.bob_id, badge_key="comic_trader").first()
            self.assertIsNotNone(alice_badge)
            self.assertIsNotNone(bob_badge)

    def test_trade_decline_and_cancel(self):
        # Testing decline by receiver and cancel by sender (:
        with self.app.app_context():
            award_card_to_user(self.alice_id, card_key="squshy_slime")
            award_card_to_user(self.alice_id, card_key="squshy_slime")

            # Trade 1: Bob declines
            _, _, trade1 = propose_trade(self.alice_id, self.bob_id, "squshy_slime")
            trade1_id = trade1.id

            # Trade 2: Alice cancels
            _, _, trade2 = propose_trade(self.alice_id, self.bob_id, "squshy_slime")
            trade2_id = trade2.id

        # Bob declines trade 1
        self.login("bob", "BobPassword123!")
        res = self.client.post(f"/messages/trade/{trade1_id}/decline", follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with self.app.app_context():
            t1 = db.session.get(CardTrade, trade1_id)
            self.assertEqual(t1.status, "declined")

        # Alice cancels trade 2
        self.login("alice", "AlicePassword123!")
        res2 = self.client.post(f"/messages/trade/{trade2_id}/cancel", follow_redirects=True)
        self.assertEqual(res2.status_code, 200)

        with self.app.app_context():
            t2 = db.session.get(CardTrade, trade2_id)
            self.assertEqual(t2.status, "cancelled")

    def test_crafting_badges_from_duplicates(self):
        # Recycling duplicates to forge badges (:
        with self.app.app_context():
            # Give Alice 4 copies of squshy_slime -> 3 duplicates!
            for _ in range(4):
                award_card_to_user(self.alice_id, card_key="squshy_slime")

            dupes = get_user_duplicates(self.alice_id)
            self.assertEqual(dupes[0]["duplicate_count"], 3)

            # Check recipe status
            status = get_crafting_recipes_status(self.alice_id)
            crafter_recipe = next(r for r in status if r["key"] == "comic_crafter")
            self.assertTrue(crafter_recipe["can_craft"])
            self.assertFalse(crafter_recipe["already_unlocked"])

        # Alice crafts the badge
        self.login("alice", "AlicePassword123!")
        res = self.client.post("/inventory/craft/comic_crafter", follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with self.app.app_context():
            # Badge should now be unlocked in UserBadge
            badge = UserBadge.query.filter_by(user_id=self.alice_id, badge_key="comic_crafter").first()
            self.assertIsNotNone(badge)

            # Duplicates should have been deducted (4 - 3 = 1 left)
            alice_slime = UserCard.query.filter_by(user_id=self.alice_id, card_key="squshy_slime").first()
            self.assertEqual(alice_slime.quantity, 1)

            # Trying to craft again with 0 duplicates must fail!
            success, msg = execute_craft(self.alice_id, "comic_crafter")
            self.assertFalse(success)

    def test_inventory_views_and_api(self):
        # Testing endpoints: /inventory, /api/inventory/my-duplicates, /inventory/test-drop (:
        self.login("alice", "AlicePassword123!")

        # 1. Main inventory page
        res = self.client.get("/inventory")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"COMIC LOOT", res.data)

        # 2. Test pull endpoint
        res_drop = self.client.post("/inventory/test-drop", follow_redirects=True)
        self.assertEqual(res_drop.status_code, 200)

        with self.app.app_context():
            inv = get_user_inventory(self.alice_id)
            self.assertEqual(len(inv), 1)

        # 3. API duplicates endpoint
        res_api = self.client.get("/api/inventory/my-duplicates")
        self.assertEqual(res_api.status_code, 200)
        data = res_api.get_json()
        self.assertIn("duplicates", data)


if __name__ == "__main__":
    unittest.main()

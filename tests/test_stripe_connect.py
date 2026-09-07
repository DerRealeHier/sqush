import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
import json

from app import create_app
from extensions import db
from models.user import User
from models.game import Game
from models.commerce import Purchase, CartItem, Tip
import config
from services.payment_service import (
    calculate_payout_split,
    fulfill_checkout,
    fulfill_tip,
    process_pending_payouts_for_developer,
)


class StripeConnectTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
            "SERVER_NAME": "localhost.localdomain",
        })
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Create developer user
        self.dev = User(
            username="test_developer",
            email="dev@sqush.io",
            role="dev",
            stripe_connect_id="acct_test123",
            stripe_connect_payouts_enabled=True,
            stripe_connect_details_submitted=True,
            stripe_connect_charges_enabled=True,
        )
        self.dev.set_password("DevPass123!")

        # Create buyer user
        self.buyer = User(
            username="test_buyer",
            email="buyer@sqush.io",
            role="user",
        )
        self.buyer.set_password("BuyerPass123!")

        db.session.add_all([self.dev, self.buyer])
        db.session.commit()

        # Create game
        self.game = Game(
            title="Super Indie Game",
            description="A very cool test game",
            price=10.00,
            genre="Action",
            developer_id=self.dev.id,
            image_path="uploads/covers/test.jpg",
            download_path="uploads/games/test.zip",
        )
        db.session.add(self.game)
        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_calculate_payout_split_standard(self):
        """Verify 90% dev payout and 10% platform fee calculation."""
        split = calculate_payout_split(10.00)
        self.assertEqual(split["dev_amount"], 9.00)
        self.assertEqual(split["platform_fee"], 1.00)
        self.assertEqual(split["dev_cents"], 900)
        self.assertEqual(split["platform_fee_cents"], 100)

    def test_calculate_payout_split_custom_amount(self):
        """Verify split on fractional values like 19.99 EUR."""
        split = calculate_payout_split(19.99)
        # 1999 cents * 10% = 200 cents fee -> 1799 cents dev
        self.assertEqual(split["dev_cents"], 1799)
        self.assertEqual(split["platform_fee_cents"], 200)
        self.assertEqual(split["dev_amount"], 17.99)
        self.assertEqual(split["platform_fee"], 2.00)

    def test_calculate_payout_split_tips(self):
        """Verify tips receive 100% payout to dev (0% fee)."""
        split = calculate_payout_split(5.00, is_tip=True)
        self.assertEqual(split["dev_amount"], 5.00)
        self.assertEqual(split["platform_fee"], 0.00)
        self.assertEqual(split["dev_cents"], 500)
        self.assertEqual(split["platform_fee_cents"], 0)

    def test_user_stripe_connect_fields(self):
        """Verify User model persists Stripe Connect fields."""
        u = db.session.get(User, self.dev.id)
        self.assertEqual(u.stripe_connect_id, "acct_test123")
        self.assertTrue(u.stripe_connect_payouts_enabled)
        self.assertTrue(u.stripe_connect_details_submitted)

    def test_purchase_payout_fields(self):
        """Verify Purchase model persists dev payout amounts and transfer ids."""
        p = Purchase(
            user_id=self.buyer.id,
            game_id=self.game.id,
            price_paid=10.00,
            dev_payout_amount=9.00,
            platform_fee_amount=1.00,
            stripe_transfer_id="tr_test123",
            payout_status="transferred",
        )
        db.session.add(p)
        db.session.commit()

        saved = db.session.get(Purchase, p.id)
        self.assertEqual(saved.dev_payout_amount, 9.00)
        self.assertEqual(saved.platform_fee_amount, 1.00)
        self.assertEqual(saved.stripe_transfer_id, "tr_test123")
        self.assertEqual(saved.payout_status, "transferred")

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_uses_destination_charge_when_dev_connected(self, mock_session_create):
        """If developer has Stripe Connect active, single game checkout must route 90% via destination charge."""
        mock_session_create.return_value = MagicMock(id="cs_test_dest_charge")

        # Login as buyer
        with self.client.session_transaction() as sess:
            sess["_user_id"] = str(self.buyer.id)

        # Temporary configure secret key for test
        with patch.dict(config.stripe_keys, {"secret_key": "sk_test_mock"}):
            res = self.client.get(f"/create-checkout-session/{self.game.id}")
            self.assertEqual(res.status_code, 200)

            # Assert destination charge was passed
            call_kwargs = mock_session_create.call_args[1]
            self.assertIn("payment_intent_data", call_kwargs)
            self.assertEqual(
                call_kwargs["payment_intent_data"]["transfer_data"]["destination"],
                "acct_test123",
            )
            # 10.00 EUR -> 100 cents (10%) platform fee
            self.assertEqual(call_kwargs["payment_intent_data"]["application_fee_amount"], 100)
            self.assertEqual(call_kwargs["metadata"]["is_destination_charge"], "true")

    @patch("stripe.Transfer.create")
    @patch("stripe.checkout.Session.retrieve")
    def test_fulfill_checkout_single_direct_destination(self, mock_retrieve, mock_transfer):
        """When a destination charge succeeds, purchase is recorded as direct payout."""
        session_obj = MagicMock()
        session_obj.id = "cs_single_dest"
        session_obj.payment_status = "paid"
        session_obj.payment_intent = "pi_single_dest"
        session_obj.metadata = {
            "user_id": str(self.buyer.id),
            "game_id": str(self.game.id),
            "is_destination_charge": "true",
        }
        mock_retrieve.return_value = session_obj

        with patch.dict(config.stripe_keys, {"secret_key": "sk_test_mock"}):
            ok = fulfill_checkout("cs_single_dest")
            self.assertTrue(ok)

            # Check purchase record
            p = Purchase.query.filter_by(stripe_checkout_session_id="cs_single_dest").first()
            self.assertIsNotNone(p)
            self.assertEqual(p.payout_status, "direct")
            self.assertEqual(p.dev_payout_amount, 9.00)
            self.assertEqual(p.platform_fee_amount, 1.00)
            # No separate transfer needed because Stripe routed it directly
            mock_transfer.assert_not_called()

    @patch("stripe.Transfer.create")
    @patch("stripe.checkout.Session.retrieve")
    def test_fulfill_checkout_cart_separate_transfers(self, mock_retrieve, mock_transfer):
        """Multi-game cart fulfillment creates separate transfers for connected developers."""
        mock_transfer.return_value = MagicMock(id="tr_cart_transfer_999")

        session_obj = MagicMock()
        session_obj.id = "cs_cart_multi"
        session_obj.payment_status = "paid"
        session_obj.payment_intent = "pi_cart_multi"
        session_obj.metadata = {
            "user_id": str(self.buyer.id),
            "cart_game_ids": json.dumps([self.game.id]),
        }
        mock_retrieve.return_value = session_obj

        with patch.dict(config.stripe_keys, {"secret_key": "sk_test_mock"}):
            with patch("config.STRIPE_SECRET_KEY", "sk_test_mock"):
                ok = fulfill_checkout("cs_cart_multi")
                self.assertTrue(ok)

                # Transfer should have been called for 9.00 EUR (900 cents)
                mock_transfer.assert_called_once()
                self.assertEqual(mock_transfer.call_args[1]["amount"], 900)
                self.assertEqual(mock_transfer.call_args[1]["destination"], "acct_test123")

                p = Purchase.query.filter_by(stripe_checkout_session_id=f"cs_cart_multi|{self.game.id}").first()
                self.assertEqual(p.payout_status, "transferred")
                self.assertEqual(p.stripe_transfer_id, "tr_cart_transfer_999")
                self.assertEqual(p.dev_payout_amount, 9.00)

    @patch("stripe.Transfer.create")
    def test_process_pending_payouts_for_developer(self, mock_transfer):
        """Retroactive backlog payout: un-transferred sales are transferred once developer connects."""
        mock_transfer.return_value = MagicMock(id="tr_backlog_101")

        # Create purchase before developer was connected
        p = Purchase(
            user_id=self.buyer.id,
            game_id=self.game.id,
            price_paid=10.00,
            dev_payout_amount=9.00,
            platform_fee_amount=1.00,
            payout_status="unconnected",
            stripe_checkout_session_id="cs_old_unconnected",
        )
        db.session.add(p)
        db.session.commit()

        with patch("config.STRIPE_SECRET_KEY", "sk_test_mock"):
            count = process_pending_payouts_for_developer(self.dev)
            self.assertEqual(count, 1)

            mock_transfer.assert_called_once()
            self.assertEqual(mock_transfer.call_args[1]["amount"], 900)

            updated_p = db.session.get(Purchase, p.id)
            self.assertEqual(updated_p.payout_status, "transferred")
            self.assertEqual(updated_p.stripe_transfer_id, "tr_backlog_101")

    def test_developer_revenue_page_renders_stripe_connect(self):
        """Developer revenue page renders Stripe Connect status, financial breakdown, and transactions."""
        with self.client.session_transaction() as sess:
            sess["_user_id"] = str(self.dev.id)

        res = self.client.get("/dashboard/revenue")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("STRIPE CONNECT (AUTOMATED PAYOUTS)", html)
        self.assertIn("PAYOUTS ACTIVE", html)
        self.assertIn("Gross Sales", html)
        self.assertIn("Dev Payouts (90%)", html)
        self.assertIn("Sqush Cut (10%)", html)


if __name__ == "__main__":
    unittest.main()

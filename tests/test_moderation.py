import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from app import create_app
from extensions import db
from models.user import User
from models.game import Game, Review
from models.ban import UserBan, ModerationScanState
from services.moderation_service import (
    execute_ban,
    unban_user,
    is_user_banned,
    is_email_banned,
    run_moderation_scan,
)


class ModerationTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
            "SECRET_KEY": "test_moderation_secret_key",
            "GROQ_API_KEY": "gsk_test_mock_key",
            "AI_MODERATION_ENABLED": True,
        })
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

            # Admin user
            self.admin = User(
                username="squshadmin",
                email="admin@sqush.dev",
                role="admin",
                email_verified=True,
                two_fa_enabled=False,
            )
            self.admin.set_password("AdminPass123!")
            db.session.add(self.admin)

            # Regular player 1
            self.user1 = User(
                username="toxicplayer",
                email="toxic@example.com",
                role="user",
                email_verified=True,
                two_fa_enabled=False,
            )
            self.user1.set_password("SecretPass123!")
            db.session.add(self.user1)

            # Regular player 2
            self.user2 = User(
                username="doxxer123",
                email="doxxer@example.com",
                role="user",
                email_verified=True,
                two_fa_enabled=False,
            )
            self.user2.set_password("SecretPass123!")
            db.session.add(self.user2)

            # Developer (permitted to scan, forbidden to ban)
            self.dev_user = User(
                username="codeninja",
                email="dev@example.com",
                role="dev",
                email_verified=True,
                two_fa_enabled=False,
            )
            self.dev_user.set_password("DevPass123!")
            db.session.add(self.dev_user)
            db.session.flush()

            # Test game
            self.game = Game(
                title="Super Game",
                genre="Action",
                price=4.99,
                download_path="uploads/test.zip",
                developer_id=self.admin.id,
            )
            db.session.add(self.game)
            db.session.commit()

            self.admin_id = self.admin.id
            self.user1_id = self.user1.id
            self.user2_id = self.user2.id
            self.dev_user_id = self.dev_user.id
            self.game_id = self.game.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_temporary_30_day_ban_for_pii(self):
        """Verify minor offenses (PII/doxxing) trigger a 30 day temporary ban."""
        with self.app.app_context():
            user = User.query.get(self.user2_id)
            ban = execute_ban(
                user=user,
                severity="minor",
                offense_category="doxxing_pii",
                reason="Leaking personal info / real name",
                evidence="Max Mustermann aus Berlin",
                content_source="review",
                content_id=1,
                banned_by="GroqAI-llama-3.3-70b-versatile",
            )
            db.session.commit()

            self.assertIsNotNone(ban)
            self.assertEqual(ban.ban_type, "temporary")
            self.assertEqual(ban.duration_days, 30)
            self.assertEqual(ban.severity, "minor")
            self.assertEqual(ban.offense_category, "doxxing_pii")
            self.assertTrue(ban.is_active)
            self.assertIsNotNone(ban.expires_at)

            # Check helper methods
            self.assertTrue(is_user_banned(user.id))
            self.assertTrue(is_email_banned(user.email))
            self.assertTrue(user.is_banned)

    def test_temporary_ban_expiration(self):
        """Verify that expired temporary bans are no longer active."""
        with self.app.app_context():
            user = User.query.get(self.user2_id)
            ban = execute_ban(
                user=user,
                severity="minor",
                offense_category="doxxing_pii",
                reason="Veröffentlichung persönlicher Daten",
            )
            # Fast forward expiration to the past
            ban.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
            db.session.commit()

            self.assertFalse(is_user_banned(user.id))
            self.assertFalse(is_email_banned(user.email))
            self.assertFalse(user.is_banned)

    def test_permanent_ban_for_hate_speech(self):
        """Verify severe offenses (hate speech / slurs) trigger a permanent ban."""
        with self.app.app_context():
            user = User.query.get(self.user1_id)
            ban = execute_ban(
                user=user,
                severity="severe",
                offense_category="hate_speech_slurs",
                reason="Rassistische Beleidigung / N-Wort.",
                evidence="N-word slur snippet",
                banned_by="GroqAI",
            )
            db.session.commit()

            self.assertIsNotNone(ban)
            self.assertEqual(ban.ban_type, "permanent")
            self.assertIsNone(ban.duration_days)
            self.assertIsNone(ban.expires_at)
            self.assertEqual(ban.severity, "severe")
            self.assertTrue(is_user_banned(user.id))
            self.assertTrue(is_email_banned(user.email))

    def test_banned_user_login_blocked(self):
        """Verify banned users cannot log in."""
        with self.app.app_context():
            user = User.query.get(self.user1_id)
            execute_ban(user=user, severity="severe", reason="Permaban test")
            db.session.commit()

        # Attempt login
        response = self.client.post(
            "/login",
            data={"username": "toxicplayer", "password": "SecretPass123!"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        # Verify page displays ban notice
        self.assertIn(b"banned", response.data)

    def test_banned_email_registration_blocked(self):
        """Verify banned email addresses cannot register new accounts."""
        with self.app.app_context():
            user = User.query.get(self.user1_id)
            execute_ban(user=user, severity="minor", reason="30 day test")
            db.session.commit()

        # Attempt registration with banned email
        response = self.client.post(
            "/register",
            data={
                "username": "brandnewaccount",
                "email": "toxic@example.com",
                "password": "ValidPassword123!",
                "confirm_password": "ValidPassword123!",
                "role": "user",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"banned", response.data)

    def test_active_session_terminated_for_banned_user(self):
        """Verify before_request kicks out users as soon as they are banned."""
        # 1. Log in successfully
        login_res = self.client.post(
            "/login",
            data={"username": "doxxer123", "password": "SecretPass123!"},
            follow_redirects=True,
        )
        self.assertEqual(login_res.status_code, 200)

        # 2. Ban user while logged in
        with self.app.app_context():
            user = User.query.get(self.user2_id)
            execute_ban(user=user, severity="minor", reason="Doxxing mid-session")
            db.session.commit()

        # 3. Next request should be intercepted and logged out
        res = self.client.get("/settings", follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"banned", res.data)

    def test_unban_user(self):
        """Verify unbanning restores access."""
        with self.app.app_context():
            user = User.query.get(self.user1_id)
            ban = execute_ban(user=user, severity="severe", reason="Accidental ban")
            db.session.commit()

            self.assertTrue(is_user_banned(user.id))

            # Unban
            success = unban_user(ban.id)
            self.assertTrue(success)
            db.session.commit()

            self.assertFalse(is_user_banned(user.id))
            self.assertFalse(is_email_banned(user.email))

    def test_public_ban_log_view(self):
        """Verify public ban log displays entries without revealing private info."""
        with self.app.app_context():
            user = User.query.get(self.user1_id)
            execute_ban(
                user=user,
                severity="severe",
                offense_category="hate_speech_slurs",
                reason="Severe racial slurs",
                evidence_snippet="SECRET_PRIVATE_INFO",
            )
            db.session.commit()

        response = self.client.get("/bans")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"BAN LOG", response.data)
        self.assertIn(b"toxicplayer", response.data)
        self.assertIn(b"PERMANENT", response.data)
        # Raw evidence / user email should not be leaked in public log
        self.assertNotIn(b"SECRET_PRIVATE_INFO", response.data)
        self.assertNotIn(b"toxic@example.com", response.data)

    @patch("services.moderation_service.requests.post")
    def test_moderation_scan_auto_bans_and_redacts(self, mock_post):
        """Verify run_moderation_scan detects violations via AI, bans user, and redacts content."""
        # Create a bad review by user1
        with self.app.app_context():
            bad_review = Review(
                game_id=self.game_id,
                user_id=self.user1_id,
                is_positive=False,
                comment="This game is terrible you f***ing [slur]!",
            )
            db.session.add(bad_review)
            db.session.commit()
            review_id = bad_review.id

        # Mock Groq API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"results": [{'
                            '"item_id": "review_' + str(review_id) + '", '
                            '"verdict": "severe", '
                            '"offense_category": "hate_speech_slur", '
                            '"public_reason": "Verwendung von rassistischen Slurs / Hate Speech", '
                            '"evidence_snippet": "[slur]"'
                            '}]}'
                        )
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        # Execute scan
        with self.app.app_context():
            result = run_moderation_scan()
            self.assertGreaterEqual(result["items_scanned"], 1)
            self.assertEqual(result["bans_issued"], 1)

            # Check that user1 is now permanently banned
            self.assertTrue(is_user_banned(self.user1_id))
            user = User.query.get(self.user1_id)
            self.assertTrue(user.is_banned)
            active_ban = user.active_ban
            self.assertEqual(active_ban.ban_type, "permanent")

            # Check that the offending review content was redacted
            review = Review.query.get(review_id)
            self.assertIn("moderated", review.comment)

    def test_developer_cannot_manually_ban_or_unban(self):
        """Verify developers are forbidden from manually banning or unbanning users."""
        self.client.post("/login", data={"username": "codeninja", "password": "DevPass123!"})

        # Dev attempts manual ban -> 403 Forbidden
        ban_res = self.client.post(
            "/admin/bans/manual",
            data={
                "identifier": "toxicplayer",
                "severity": "minor",
                "offense_category": "custom",
                "reason": "Dev trying to ban",
            },
        )
        self.assertEqual(ban_res.status_code, 403)

        # Admin created ban, dev attempts unban -> 403 Forbidden
        with self.app.app_context():
            user = User.query.get(self.user1_id)
            ban = execute_ban(user=user, severity="minor", reason="Admin ban")
            db.session.commit()
            ban_id = ban.id

        unban_res = self.client.post(f"/admin/bans/{ban_id}/unban")
        self.assertEqual(unban_res.status_code, 403)

    def test_developer_can_trigger_moderation_scan(self):
        """Verify developers ARE allowed to run the Groq AI scan."""
        self.client.post("/login", data={"username": "codeninja", "password": "DevPass123!"})
        with patch("routes.ban_log.run_moderation_scan", return_value={"status": "success", "items_scanned": 0, "bans_issued": 0}):
            scan_res = self.client.post("/admin/moderation/run-scan", follow_redirects=True)
            self.assertEqual(scan_res.status_code, 200)

    def test_admin_can_manually_ban_and_unban(self):
        """Verify administrators CAN manually ban and unban users."""
        self.client.post("/login", data={"username": "squshadmin", "password": "AdminPass123!"})
        ban_res = self.client.post(
            "/admin/bans/manual",
            data={
                "identifier": "toxicplayer",
                "severity": "severe",
                "offense_category": "hate_speech_slur",
                "reason": "Manual admin ban",
            },
            follow_redirects=True,
        )
        self.assertEqual(ban_res.status_code, 200)
        with self.app.app_context():
            self.assertTrue(is_user_banned(self.user1_id))
            ban = UserBan.query.filter_by(user_id=self.user1_id, is_active=True).first()
            ban_id = ban.id

        unban_res = self.client.post(f"/admin/bans/{ban_id}/unban", follow_redirects=True)
        self.assertEqual(unban_res.status_code, 200)
        with self.app.app_context():
            self.assertFalse(is_user_banned(self.user1_id))


if __name__ == "__main__":
    unittest.main()

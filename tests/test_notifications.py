import unittest
from datetime import datetime, timezone
from app import create_app
from extensions import db
from models.user import User, Notification


class NotificationsTestCase(unittest.TestCase):
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

            self.user = User(
                username="notifuser",
                email="notif@sqush.dev",
                role="user",
                email_verified=True,
                two_fa_enabled=False,
            )
            self.user.set_password("Password123!")
            db.session.add(self.user)
            db.session.commit()

            self.user_id = self.user.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def login(self):
        res = self.client.post("/login", data={
            "username": "notifuser",
            "password": "Password123!"
        }, follow_redirects=True)
        # Clear any auto-awarded badge notifications from login so tests have clean baseline
        with self.app.app_context():
            Notification.query.filter_by(user_id=self.user_id).delete()
            db.session.commit()
        return res

    def test_all_new_notifications_loaded_when_more_than_five(self):
        """Verify that when a user has more than 5 unread notifications, ALL of them are loaded."""
        self.login()

        with self.app.app_context():
            for i in range(8):
                n = Notification(
                    user_id=self.user_id,
                    message=f"New notification {i+1}",
                    type="system",
                    is_read=False
                )
                db.session.add(n)
            db.session.commit()

        # Fetch a page that uses the context processor and notification dropdown
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)

        # All 8 new notifications should be rendered in the HTML
        for i in range(8):
            self.assertIn(f"New notification {i+1}", res.get_data(as_text=True))

        # Check unread count badge in HTML
        self.assertIn("8 NEW", res.get_data(as_text=True))

    def test_notifications_page_and_filters(self):
        """Verify /notifications page renders all notifications and filters unread ones."""
        self.login()

        with self.app.app_context():
            # Create 3 unread and 2 read notifications
            for i in range(3):
                db.session.add(Notification(
                    user_id=self.user_id,
                    message=f"Unread message {i+1}",
                    type="system",
                    is_read=False
                ))
            for i in range(2):
                db.session.add(Notification(
                    user_id=self.user_id,
                    message=f"Read message {i+1}",
                    type="system",
                    is_read=True
                ))
            db.session.commit()

        # All filter
        res_all = self.client.get("/notifications?filter=all")
        self.assertEqual(res_all.status_code, 200)
        content_all = res_all.get_data(as_text=True)
        self.assertIn("Unread message 1", content_all)
        self.assertIn("Read message 1", content_all)
        self.assertIn("ALL (5)", content_all)
        self.assertIn("NEW (3)", content_all)

        # Unread filter (alle neuen anzeigen)
        res_unread = self.client.get("/notifications?filter=unread")
        self.assertEqual(res_unread.status_code, 200)
        content_unread = res_unread.get_data(as_text=True)
        page_cards_html = content_unread.split('<!-- Notification List -->')[1].split('<!-- /Notification List -->')[0]
        self.assertIn("Unread message 1", page_cards_html)
        self.assertIn("Unread message 2", page_cards_html)
        self.assertIn("Unread message 3", page_cards_html)
        self.assertNotIn("Read message 1", page_cards_html)
        self.assertNotIn("Read message 2", page_cards_html)

    def test_mark_all_notifications_read(self):
        """Verify mark-all-read marks all unread notifications as read."""
        self.login()

        with self.app.app_context():
            for i in range(5):
                db.session.add(Notification(
                    user_id=self.user_id,
                    message=f"Unread {i+1}",
                    type="system",
                    is_read=False
                ))
            db.session.commit()

        res = self.client.post("/notifications/mark-all-read", follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with self.app.app_context():
            unread = Notification.query.filter_by(user_id=self.user_id, is_read=False).count()
            self.assertEqual(unread, 0)

    def test_mark_single_notification_read(self):
        """Verify mark-read marks a specific notification as read."""
        self.login()

        with self.app.app_context():
            notif = Notification(
                user_id=self.user_id,
                message="Single unread",
                type="system",
                is_read=False
            )
            db.session.add(notif)
            db.session.commit()
            notif_id = notif.id

        res = self.client.post(f"/notification/mark-read/{notif_id}", follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with self.app.app_context():
            updated = db.session.get(Notification, notif_id)
            self.assertTrue(updated.is_read)


if __name__ == "__main__":
    unittest.main()

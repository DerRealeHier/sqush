import unittest
from datetime import datetime, timezone
from app import create_app
from extensions import db
from models.user import User, Notification
from models.game import Game
from models.roadmap import RoadmapItem, RoadmapVote, RoadmapComment


class RoadmapTestCase(unittest.TestCase):
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

            # Create Developer User (2FA disabled for simple testing)
            self.dev = User(
                username="testdev",
                email="dev@sqush.io",
                role="dev",
                email_verified=True,
                two_fa_enabled=False,
            )
            self.dev.set_password("DevPassword123!")
            db.session.add(self.dev)

            # Create Community Player User
            self.player = User(
                username="testplayer",
                email="player@sqush.io",
                role="user",
                email_verified=True,
                two_fa_enabled=False,
            )
            self.player.set_password("PlayerPassword123!")
            db.session.add(self.player)

            # Create another Player User
            self.other_player = User(
                username="otherplayer",
                email="other@sqush.io",
                role="user",
                email_verified=True,
                two_fa_enabled=False,
            )
            self.other_player.set_password("OtherPassword123!")
            db.session.add(self.other_player)

            db.session.commit()

            # Create a Game owned by testdev
            self.game = Game(
                title="Super Comic Quest",
                genre="Action",
                tags="Action, Indie",
                price=9.99,
                download_path="uploads/fake.zip",
                developer_id=self.dev.id,
            )
            db.session.add(self.game)
            db.session.commit()

            self.dev_id = self.dev.id
            self.player_id = self.player.id
            self.other_player_id = self.other_player.id
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

    def test_public_roadmap_view(self):
        #Guests can view the roadmap without logging in.
        with self.app.app_context():
            item = RoadmapItem(
                game_id=self.game_id,
                author_id=self.dev_id,
                title="Level 2 Boss",
                status="planned",
                category="feature",
                is_dev_post=True,
            )
            db.session.add(item)
            db.session.commit()

        response = self.client.get(f"/game/{self.game_id}/roadmap")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Super Comic Quest", response.data)
        self.assertIn(b"Level 2 Boss", response.data)
        self.assertIn(b"PLANNED", response.data)
        self.assertIn(b"IN PROGRESS", response.data)
        self.assertIn(b"DONE", response.data)

    def test_create_roadmap_item_dev(self):
        """Developer can create roadmap cards directly into In Progress or Done."""
        self.login("testdev", "DevPassword123!")

        res = self.client.post(
            f"/game/{self.game_id}/roadmap/item",
            data={
                "title": "Gamepad Rumble Support",
                "description": "Adding haptic feedback for Xbox & PS controllers",
                "category": "feature",
                "status": "in_progress",
            },
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)

        with self.app.app_context():
            item = RoadmapItem.query.filter_by(title="Gamepad Rumble Support").first()
            self.assertIsNotNone(item)
            self.assertEqual(item.status, "in_progress")
            self.assertEqual(item.category, "feature")
            self.assertTrue(item.is_dev_post)
            self.assertEqual(item.upvotes_count, 1)  # Auto-vote by author

    def test_create_roadmap_item_community_notifies_dev(self):
        """Community players can report bugs, which start in 'planned' and notify the developer."""
        self.login("testplayer", "PlayerPassword123!")

        res = self.client.post(
            f"/game/{self.game_id}/roadmap/item",
            data={
                "title": "Inventory crash on equip",
                "description": "When equipping sword in slot 3, game freezes.",
                "category": "bug",
                "status": "done",  # Attempt to bypass status: should be ignored for non-devs!
            },
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)

        with self.app.app_context():
            item = RoadmapItem.query.filter_by(title="Inventory crash on equip").first()
            self.assertIsNotNone(item)
            self.assertEqual(item.status, "planned")  # Enforced to 'planned'
            self.assertEqual(item.category, "bug")
            self.assertFalse(item.is_dev_post)

            # Dev should have received a notification
            notif = Notification.query.filter_by(user_id=self.dev_id, type="roadmap_submission").first()
            self.assertIsNotNone(notif)
            self.assertIn("testplayer submitted a Bug Report", notif.message)

    def test_upvoting_toggle(self):
        """Upvote adds 1 vote; upvoting again toggles off."""
        with self.app.app_context():
            item = RoadmapItem(
                game_id=self.game_id,
                author_id=self.dev_id,
                title="Online Leaderboard",
                status="planned",
                category="feature",
                upvotes_count=1,
            )
            db.session.add(item)
            db.session.commit()
            item_id = item.id

        self.login("testplayer", "PlayerPassword123!")

        # Vote #1 -> Upvotes should become 2
        res = self.client.post(f"/roadmap/item/{item_id}/vote")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["voted"])
        self.assertEqual(data["upvotes_count"], 2)

        # Vote #2 (same user) -> Toggles off, upvotes should return to 1
        res = self.client.post(f"/roadmap/item/{item_id}/vote")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertFalse(data["voted"])
        self.assertEqual(data["upvotes_count"], 1)

    def test_status_change_permissions_and_notifications(self):
        #Only the developer can change item status; author gets notified on progress.
        with self.app.app_context():
            item = RoadmapItem(
                game_id=self.game_id,
                author_id=self.player_id,
                title="Audio sliders in options",
                status="planned",
                category="feature",
            )
            db.session.add(item)
            db.session.commit()
            item_id = item.id

        # Player tries to move status -> 403 Forbidden
        self.login("testplayer", "PlayerPassword123!")
        res = self.client.post(f"/roadmap/item/{item_id}/status", json={"status": "in_progress"})
        self.assertEqual(res.status_code, 403)

        # Developer moves status to in_progress -> 200 OK & notifies player
        self.login("testdev", "DevPassword123!")
        res = self.client.post(f"/roadmap/item/{item_id}/status", json={"status": "in_progress"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["new_status"], "in_progress")

        with self.app.app_context():
            updated_item = db.session.get(RoadmapItem, item_id)
            self.assertEqual(updated_item.status, "in_progress")

            # Notification for player
            notif = Notification.query.filter_by(user_id=self.player_id, type="roadmap_status").first()
            self.assertIsNotNone(notif)
            self.assertIn("Audio sliders in options", notif.message)
            self.assertIn("In Progress", notif.message)

    def test_commenting_and_detail_endpoint(self):
        """Users can post comments and retrieve card details via the API."""
        with self.app.app_context():
            item = RoadmapItem(
                game_id=self.game_id,
                author_id=self.player_id,
                title="Linux Build",
                status="planned",
                category="feature",
                description="Please consider Native Linux release via Proton or native binary.",
            )
            db.session.add(item)
            db.session.commit()
            item_id = item.id

        self.login("testdev", "DevPassword123!")

        res = self.client.post(f"/roadmap/item/{item_id}/comment", json={
            "content": "We tested on SteamDeck and it works great! Native build coming soon."
        })
        self.assertEqual(res.status_code, 200)

        # Retrieve card detail
        detail_res = self.client.get(f"/roadmap/item/{item_id}/detail")
        self.assertEqual(detail_res.status_code, 200)
        detail = detail_res.get_json()
        self.assertEqual(detail["title"], "Linux Build")
        self.assertEqual(len(detail["comments"]), 1)
        self.assertEqual(detail["comments"][0]["author"], "testdev")
        self.assertTrue(detail["comments"][0]["author_is_dev"])

    def test_delete_permissions(self):
        #Author or Developer can delete an item; unrelated user cannot.
        with self.app.app_context():
            item = RoadmapItem(
                game_id=self.game_id,
                author_id=self.player_id,
                title="Typo in main menu",
                status="planned",
                category="bug",
            )
            db.session.add(item)
            db.session.commit()
            item_id = item.id

        # Other player cannot delete -> 403
        self.login("otherplayer", "OtherPassword123!")
        res = self.client.post(f"/roadmap/item/{item_id}/delete")
        self.assertEqual(res.status_code, 403)

        # Author can delete -> 200
        self.login("testplayer", "PlayerPassword123!")
        res = self.client.post(f"/roadmap/item/{item_id}/delete", json={})
        self.assertEqual(res.status_code, 200)

        with self.app.app_context():
            deleted = db.session.get(RoadmapItem, item_id)
            self.assertIsNone(deleted)

    def test_notification_redirect_to_roadmap(self):
        """Clicking a roadmap notification navigates directly to the game roadmap."""
        with self.app.app_context():
            notif = Notification(
                user_id=self.player_id,
                message=f"Update on '{self.game.title}': Your item 'Controller support' is now 'In Progress'!",
                type="roadmap_status",
            )
            db.session.add(notif)
            db.session.commit()
            notif_id = notif.id

        self.login("testplayer", "PlayerPassword123!")
        res = self.client.get(f"/notification/read/{notif_id}")
        self.assertEqual(res.status_code, 302)
        self.assertIn(f"/game/{self.game_id}/roadmap", res.headers["Location"])


if __name__ == "__main__":
    unittest.main()

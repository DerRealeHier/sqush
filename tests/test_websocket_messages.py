import unittest
from app import create_app
from extensions import db, socketio
from models.user import User, Notification
from models.message import DirectMessage


class WebSocketMessagesTestCase(unittest.TestCase):
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

            self.user1 = User(
                username="alice",
                email="alice@sqush.dev",
                role="user",
                email_verified=True,
                two_fa_enabled=False,
            )
            self.user1.set_password("Password123!")
            db.session.add(self.user1)

            self.user2 = User(
                username="bob",
                email="bob@sqush.dev",
                role="user",
                email_verified=True,
                two_fa_enabled=False,
            )
            self.user2.set_password("Password123!")
            db.session.add(self.user2)
            db.session.commit()

            self.user1_id = self.user1.id
            self.user2_id = self.user2.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_send_and_receive_direct_message_websocket(self):
        # Log in alice
        client_alice = self.app.test_client()
        client_alice.post("/login", data={"username": "alice", "password": "Password123!"}, follow_redirects=True)

        # Log in bob
        client_bob = self.app.test_client()
        client_bob.post("/login", data={"username": "bob", "password": "Password123!"}, follow_redirects=True)

        # Connect sockets
        socket_alice = socketio.test_client(self.app, flask_test_client=client_alice)
        socket_bob = socketio.test_client(self.app, flask_test_client=client_bob)

        self.assertTrue(socket_alice.is_connected())
        self.assertTrue(socket_bob.is_connected())

        # Alice sends message to Bob
        res = socket_alice.emit("send_direct_message", {
            "recipient_id": self.user2_id,
            "content": "Hey Bob, was geht ab!"
        }, callback=True)

        self.assertIsNotNone(res)
        self.assertEqual(res.get("status"), "success")

        # Verify Bob received the event
        received_bob = socket_bob.get_received()
        new_msg_events = [e for e in received_bob if e["name"] == "new_message"]
        self.assertEqual(len(new_msg_events), 1)
        self.assertEqual(new_msg_events[0]["args"][0]["content"], "Hey Bob, was geht ab!")
        self.assertEqual(new_msg_events[0]["args"][0]["sender_username"], "alice")

        # Verify Alice received message_sent confirmation
        received_alice = socket_alice.get_received()
        sent_events = [e for e in received_alice if e["name"] == "message_sent"]
        self.assertEqual(len(sent_events), 1)
        self.assertEqual(sent_events[0]["args"][0]["content"], "Hey Bob, was geht ab!")

        # Verify stored in DB
        with self.app.app_context():
            msg = DirectMessage.query.filter_by(sender_id=self.user1_id, recipient_id=self.user2_id).first()
            self.assertIsNotNone(msg)
            self.assertEqual(msg.content, "Hey Bob, was geht ab!")
            self.assertFalse(msg.is_read)

        # Bob marks message as read
        socket_bob.emit("mark_read", {"sender_id": self.user1_id})

        with self.app.app_context():
            msg = DirectMessage.query.get(msg.id)
            self.assertTrue(msg.is_read)

        # Alice receives messages_read event
        received_alice_after_read = socket_alice.get_received()
        read_events = [e for e in received_alice_after_read if e["name"] == "messages_read"]
        self.assertEqual(len(read_events), 1)
        self.assertEqual(read_events[0]["args"][0]["reader_id"], self.user2_id)

        # Alice deletes the message
        del_res = socket_alice.emit("delete_message", {"message_id": msg.id}, callback=True)
        self.assertEqual(del_res.get("status"), "success")

        # Both receive message_deleted event
        bob_del = [e for e in socket_bob.get_received() if e["name"] == "message_deleted"]
        self.assertEqual(len(bob_del), 1)
        self.assertEqual(bob_del[0]["args"][0]["message_id"], msg.id)

        with self.app.app_context():
            deleted_check = DirectMessage.query.get(msg.id)
            self.assertIsNone(deleted_check)

        socket_alice.disconnect()
        socket_bob.disconnect()


if __name__ == "__main__":
    unittest.main()

import unittest

from flask import Flask

from src.routes import chat_routes as chat_routes_module
from src.routes.chat_routes import chat_bp, init_chat_routes


class FakeChatManager:
    def __init__(self):
        self.current_room = None
        self.join_result = True
        self.send_result = True
        self.join_calls = []
        self.sent_messages = []
        self.create_calls = []
        self.participants = [{"id": "user-2", "name": "Teammate"}]

    def join_room(self, room, password):
        self.join_calls.append((room, password))
        if self.join_result:
            self.current_room = room
        return self.join_result

    def send_message(self, message):
        self.sent_messages.append(message)
        return self.send_result

    def create_room(self, name, password):
        self.create_calls.append((name, password))
        self.current_room = "created-room"
        return {
            "id": "created-room",
            "name": name,
            "type": "CHAT",
            "creator": "Test User",
        }

    def list_participants(self):
        return self.participants


class ChatRoomRouteTests(unittest.TestCase):
    def setUp(self):
        self.previous_manager = chat_routes_module.chat_manager
        self.previous_rooms = chat_routes_module.rooms
        self.manager = FakeChatManager()
        self.rooms = {
            "z-room": {
                "id": "z-room",
                "name": "Zulu room",
                "type": "CHAT",
                "password": "must-not-leak",
            },
            "a-room": {
                "id": "a-room",
                "name": "Alpha room",
                "type": "CHAT",
            },
        }
        init_chat_routes(self.manager, self.rooms)
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True)
        self.app.register_blueprint(chat_bp)
        self.client = self.app.test_client()

    def tearDown(self):
        init_chat_routes(self.previous_manager, self.previous_rooms)

    def test_room_catalog_is_sorted_safe_and_reports_the_active_room(self):
        self.manager.current_room = "z-room"

        response = self.client.get("/api/rooms")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["current_room"], "z-room")
        self.assertEqual(
            payload["rooms"],
            [
                {"id": "a-room", "name": "Alpha room", "type": "CHAT"},
                {"id": "z-room", "name": "Zulu room", "type": "CHAT"},
            ],
        )
        self.assertNotIn("password", response.get_data(as_text=True))

    def test_sending_is_gated_until_a_room_is_active(self):
        response = self.client.post("/send_message", data={"message": "Hello"})

        self.assertEqual(response.status_code, 409)
        self.assertIn("Join or create", response.get_json()["error"])
        self.assertEqual(self.manager.sent_messages, [])

        self.manager.current_room = "a-room"
        response = self.client.post("/send_message", data={"message": "Hello"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.manager.sent_messages, ["Hello"])

    def test_send_failure_is_not_reported_as_success(self):
        self.manager.current_room = "a-room"
        self.manager.send_result = False

        response = self.client.post("/send_message", data={"message": "Hello"})

        self.assertEqual(response.status_code, 502)
        self.assertIn("could not send", response.get_json()["error"])

    def test_join_forwards_the_password_and_surfaces_rejection(self):
        response = self.client.post(
            "/join_room",
            json={"room": "a-room", "password": "correct horse"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.manager.join_calls, [("a-room", "correct horse")])
        self.assertEqual(self.manager.current_room, "a-room")

        self.manager.join_result = False
        response = self.client.post(
            "/join_room",
            json={"room": "z-room", "password": "wrong"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("password", response.get_json()["error"])
        self.assertEqual(self.manager.current_room, "a-room")

    def test_room_actions_fail_cleanly_without_a_connected_manager(self):
        init_chat_routes(None, self.rooms)

        join_response = self.client.post("/join_room", json={"room": "a-room"})
        create_response = self.client.post(
            "/create_room",
            json={"roomName": "New room"},
        )
        participants_response = self.client.get("/api/room/participants")

        self.assertEqual(join_response.status_code, 503)
        self.assertEqual(create_response.status_code, 503)
        self.assertEqual(participants_response.status_code, 200)
        self.assertEqual(participants_response.get_json(), [])

    def test_creating_a_room_updates_the_catalog_and_active_room(self):
        response = self.client.post(
            "/create_room",
            json={"roomName": "Delivery", "roomPassword": "secret"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.manager.create_calls, [("Delivery", "secret")])
        self.assertEqual(self.manager.current_room, "created-room")
        self.assertIn("created-room", self.rooms)

        catalog = self.client.get("/api/rooms").get_json()
        self.assertEqual(catalog["current_room"], "created-room")
        self.assertIn(
            {"id": "created-room", "name": "Delivery", "type": "CHAT"},
            catalog["rooms"],
        )


if __name__ == "__main__":
    unittest.main()

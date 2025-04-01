import grpc
import threading
import traceback
from flask_socketio import SocketIO, emit
from src.global_logger import GlobalLogger
from src.config_handler import ConfigHandler
from src.db_handler import ChatHistory
from src.db_utils import get_default_db_path
from src.kasugai_client import KasugaiClient
from protos.kasugai_pb2 import RoomType

class ChatManager:
    def __init__(self, app, user_name):
        self.logger = GlobalLogger.get_logger('ChatManager')
        self.config = ConfigHandler()
        self.chat_history = ChatHistory(get_default_db_path())
        self.socketio = SocketIO(app, async_mode='threading')
        self.client = KasugaiClient(
            host=self.config.get('WebServer', 'kasaddress'),
            port=self.config.get('WebServer', 'kasport')
        )

        self.user = self.register_user(user_name)
        self.current_room = None

    def register_user(self, name):
        try:
            user = self.client.register_user(name)
            self.logger.info(f"User registered: {user.id.uuid}, {user.name}")
            return user
        except Exception as e:
            self.logger.error(f"Failed to register client: {e}")
            return None

    def create_room(self, room_name, password):
        try:
            room_id = self.client.create_room(room_name, password, RoomType.CHAT, self.user.id.uuid)
            self.logger.info(f"Room created with ID: {room_id.uuid}")
            response = self.client.join_room(room_id, password)
            self.logger.info(f"Joined room: {response.success}, {response.message}")
        except Exception as e:
            self.logger.error(f"Failed to create room: {e}")

    def join_room(self, room_name, password=''):
        try:
            response = self.client.join_room(room_name, password)
            self.logger.info(f"Joined room: {response.success}, {response.message}")
            self.start_listening()
        except Exception as e:
            self.logger.error(f"Failed to join room: {e}")

    def send_message(self, content):
        try:
            response = self.client.send_text_message(content)
            self.logger.info(f"Send Message: Success={response.success}, Message={response.message}")
            # optionally save history
        except grpc.RpcError as e:
            self.logger.error(f"gRPC Error sending message: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error sending message: {str(e)}")

    def start_listening(self):
        listener_thread = threading.Thread(target=self.listen_for_messages, daemon=True)
        listener_thread.start()

    def listen_for_messages(self):
        while True:
            try:
                for message in self.client.receive_text_messages():
                    self.logger.info(f"Received: {message.senderId.uuid}: {message.content}")
                    self.socketio.emit('new_message', {
                        'sender': message.senderId.uuid,
                        'content': message.content
                    })
                    self.chat_history.add_message(
                        name=message.senderId.uuid,
                        message=message.content,
                        time=str(message.timestamp.ToDatetime())
                    )
            except grpc.RpcError as e:
                self.logger.error(f"gRPC stream error: {e.code()}: {e.details()}")
            except Exception as e:
                self.logger.error(f"Unexpected receive error: {str(e)}")
                self.logger.error(traceback.format_exc())

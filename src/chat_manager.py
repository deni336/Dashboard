import grpc
import threading
import traceback
from flask_socketio import SocketIO
from src.global_logger import GlobalLogger
from src.config_handler import ConfigHandler
from src.db_handler import ChatHistory
from src.db_utils import get_default_db_path
from src.kasugai_client import KasugaiClient
from kasugai_server.python.kasugai_pb2 import RoomType
from src.message_processor import MessageProcessor

class ChatManager:
    def __init__(self, app, user_name, batch_size=10, flush_interval=1.0):
        self.logger = GlobalLogger.get_logger('ChatManager')
        self.config = ConfigHandler()
        self.chat_history = ChatHistory(get_default_db_path())
        # Setup SocketIO
        self.socketio = SocketIO(app, async_mode='threading')
        # Initialize gRPC client
        self.client = KasugaiClient(
            host=self.config.get('WebServer', 'kasaddress'),
            port=self.config.get('WebServer', 'kasport')
        )
        # Initialize message processor for batching and persistence
        self.processor = MessageProcessor(
            self.socketio,
            self.chat_history,
            batch_size=batch_size,
            flush_interval=flush_interval
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
            room_id = self.client.create_room(
                name=room_name,
                password=password,
                room_type=RoomType.CHAT,
                creator_id=self.user.id.uuid
            )
            self.logger.info(f"Room created with ID: {room_id.uuid}")

            # Join the newly created room
            response = self.client.join_room(room_id, password)
            self.logger.info(f"Joined room: {response.success}, {response.message}")

            return {
                "id": room_id.uuid,
                "name": room_name,
                "type": "CHAT",
                "creator": self.user.name
            }

        except Exception as e:
            self.logger.error(f"Failed to create room: {e}")
            return None

    def join_room(self, room_name, password=''):
        try:
            response = self.client.join_room(room_name, password)
            self.logger.info(f"Joined room: {response.success}, {response.message}")
            # Start listening for batched messages
            self.start_batch_listening()
        except Exception as e:
            self.logger.error(f"Failed to join room: {e}")

    def send_message(self, content):
        try:
            response = self.client.send_text_message(content)
            self.logger.info(f"Send Message: Success={response.success}, Message={response.message}")
        except grpc.RpcError as e:
            self.logger.error(f"gRPC Error sending message: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error sending message: {str(e)}")

    def start_batch_listening(self):
        listener_thread = threading.Thread(
            target=self.batch_listen_for_messages,
            daemon=True
        )
        listener_thread.start()

    def batch_listen_for_messages(self):
        """
        Listens to incoming messages in batches and enqueues them to the processor.
        """
        while True:
            try:
                for batch in self.client.receive_text_message_batches(batch_size=self.processor.batch_size):
                    for message in batch:
                        self.logger.info(f"Queued message from {message.senderId.uuid}")
                        self.processor.queue.put_nowait(message)
            except grpc.RpcError as e:
                self.logger.error(f"gRPC stream error: {e.code()}: {e.details()}")
            except Exception as e:
                self.logger.error(f"Unexpected error in batch receive: {str(e)}")
                self.logger.error(traceback.format_exc())

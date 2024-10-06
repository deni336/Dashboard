import grpc
import threading
import asyncio
from time import time, sleep
from protos.kasugai_pb2 import *
from protos.kasugai_pb2_grpc import *
from chat_history import ChatHistory
from global_logger import GlobalLogger
from kasugai_client import KasugaiClient
from config_manager import ConfigManager
import const
import traceback
from flask_socketio import SocketIO, emit

class ChatManager:
    def __init__(self, app, name):
        self.logger = GlobalLogger.get_logger('ChatManager')
        self.config_manager = ConfigManager()
        self.client = KasugaiClient(host=self.config_manager.get('WebServer', 'kasaddress'), port=self.config_manager.get('WebServer', 'kasport'))
        self.active_users = []  # Keep track of active users
        self.history = ChatHistory()
        self.register_client(name)
        self.socketio = SocketIO(app)
        #self.socketio.run(app, host=self.config_manager.get('WebServer', 'address'), port=self.config_manager.get('WebServer', 'port'))

    # User registration
    def register_client(self, name):
        try:
            self.user = self.client.register_user(name) # Need to use OS.getlogin or something to show the actual username of the user
            self.logger.info(f"User registered: {self.user.id.uuid}, {self.user.name}")
        except Exception as e:
            self.logger.error(f'Failed to register client: {e}')

    def create_room(self, room, password):
        try:
            # Create a room
            creater_id = self.user.id.uuid
            room_id = self.client.create_room(room, password, kasugai__pb2.RoomType.CHAT, creater_id)
            self.logger.info(f"Room created with ID: {room_id.uuid}")
            response = self.client.join_room(room_id, password='')
            self.logger.info(f"Joining room: {response.success}, {response.message}")
        except Exception as e:
            self.logger.error(f'Failed to create room: {e}')

    def join_room(self, room, password):
        try:
            # Join the room
            response = self.client.join_room(room)
            self.logger.info(f"Joining room: {response.success}, {response.message}")
            listener_thread = threading.Thread(target=self.listen_for_messages, daemon=True)
            listener_thread.start()
        except Exception as e:
            self.logger.error(f'Failed to join room: {e}')
        
    def send_message(self, content):
        try:
            ack = self.chat_stub.SendMessage(content)
            self.logger.info(f"Send Message: Success={ack.success}, Message={ack.message}")
            # ChatHistory.add_message(const.CLIENT_ID, content, message.timestamp)
        except grpc.RpcError as e:
            self.logger.error(f"Error sending message: {e}")

    def listen_for_messages(self):
        """
        Listen for incoming messages from the server and handle them.
        Emit new messages to the frontend via SocketIO.
        """
        while True:
            try:
                for message in self.client.receive_text_messages():
                    self.logger.info(f"Received message from {message.senderId.uuid}: {message.content}")
                    self.socketio.emit(message.content)
                    
            except grpc.RpcError as e:
                self.logger.error(f"gRPC Error in receive_messages: {e.code()}: {e.details()}")
            except Exception as e:
                self.logger.error(f"Unexpected error in receive_messages: {str(e)}")
                self.logger.error(traceback.format_exc())

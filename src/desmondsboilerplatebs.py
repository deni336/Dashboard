import grpc
import threading
import asyncio
from time import time, sleep
import protos.kasugai_pb2 as pb2
import protos.kasugai_pb2_grpc as gpb2
from chat_history import ChatHistory
from kasugai_client import KasugaiClient
import const

# Have the address hard coded need to change later
class ChatManager:
    def __init__(self, server_address):
        self.client = KasugaiClient(host='localhost', port=8008)
        self.active_users = []  # Keep track of active users
        self.message_queue = []
        self.is_running = True
        self.history = ChatHistory()
        self.register_client()
        self.receive_messages()

    # User registration
    def register_client(self):
        # we need to figure this out register > create room > join room
        # Register a user
        user = client.register_user("Alice")
        print(f"User registered: {user.id.uuid}, {user.name}")

        # Create a room
        room_id = client.create_room("General", RoomType.CHAT)
        print(f"Room created with ID: {room_id.uuid}")

        # Join the room
        response = client.join_room(room_id)
        print(f"Joining room: {response.success}, {response.message}")

    def send_message(self, content):
        self.client.send_text_message(content)

    def receive_messages():
        try:
            for message in client.receive_text_messages():
                print(f"Received message from {message.senderId.uuid}: {message.content}")
        except grpc.RpcError as e:
            print(f"gRPC Error in receive_messages: {e.code()}: {e.details()}")
        except Exception as e:
            print(f"Unexpected error in receive_messages: {str(e)}")
            print(traceback.format_exc())

    

    # This is an example function of how to use the kasugai_client class if examplefunction() was the main() 
    def examplefunction():

        # first connect to server
        client = KasugaiClient(host='localhost', port=8008)
            # then:
        try:
            # Register a user
            user = client.register_user("Alice")
            print(f"User registered: {user.id.uuid}, {user.name}")

            # Create a room
            room_id = client.create_room("General", RoomType.CHAT)
            print(f"Room created with ID: {room_id.uuid}")

            # Join the room
            response = client.join_room(room_id)
            print(f"Joining room: {response.success}, {response.message}")

            # Start receiving messages in a separate thread
            threading.Thread(target=receive_messages, daemon=True).start()

            # Send a message
            client.send_text_message("Hello, World!")

            
            # Leave the room
            response = client.leave_room()
            print(f"Leaving room: {response.success}, {response.message}")

        except Exception as e:
            print(f"An error occurred: {str(e)}")
            print(traceback.format_exc())
        finally:
            client.close()
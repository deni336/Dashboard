import grpc
import threading
from time import time, sleep
import protos.kasugai_pb2 as pb2
import protos.kasugai_pb2_grpc as gpb2
from chat_history import ChatHistory
from flask_socketio import SocketIO

from webserver import WebServer

# Initialize SocketIO with Flask
socketio = SocketIO(WebServer.app)
socketio.run(WebServer.app, host='0.0.0.0', port=8008)

class KasugaiClient:
    def __init__(self, server_address):
        # Create a gRPC channel and stub
        self.channel = grpc.insecure_channel(server_address)
        self.chat_stub = gpb2.ChatServiceStub(self.channel)
        self.file_stub = gpb2.FileTransferServiceStub(self.channel)

    # User registration
    def register_client(self, user_id, name):
        user = pb2.User(uuid=pb2.Id(uuid=user_id), name=name)
        ack = self.chat_stub.RegisterClient(user)
        print(f"Register Client: Success={ack.success}, Message={ack.message}")

    def send_message(self, sender_id, recipient_id, content):
        try:
            message = pb2.Message(
                messageId=pb2.Id(uuid="message-" + str(time())),
                senderId=sender_id,
                recipientId=recipient_id,
                content=content,
                timestamp=int(time())
            )
            ack = self.chat_stub.SendMessage(message)
            print(f"Send Message: Success={ack.success}, Message={ack.message}")
            ChatHistory.add_message(sender_id, content, message.timestamp)
        except grpc.RpcError as e:
            print(f"Error sending message: {e}")


    @socketio.on('send_message')
    def handle_send_message(data):
        sender_id = "your_sender_id"  # Replace with actual sender's UUID
        recipient_id = "your_recipient_id"  # Replace with actual recipient's UUID
        content = data['content']

        # Use the KasugaiClient to send the message
        kasugai_client = KasugaiClient(server_address='99.108.66.132:8008')
        kasugai_client.send_message(sender_id, recipient_id, content)
        
        # Optionally emit a confirmation back to the frontend
        socketio.emit('message_sent', {'content': content, 'status': 'sent'})


class ChatManager:
    def __init__(self, server_address, user_id):
        self.channel = grpc.insecure_channel(server_address)
        self.chat_stub = gpb2.ChatServiceStub(self.channel)
        self.user_id = user_id  # User UUID
        self.active_users = []  # Keep track of active users
        self.message_queue = []
        self.is_running = True
        self.history = ChatHistory()
        self.start()

    def listen_for_messages(self):
        """
        Listen for incoming messages from the server and handle them.
        Emit new messages to the frontend via SocketIO.
        """
        try:
            request = pb2.Id(uuid=self.user_id)
            for message in self.chat_stub.ReceiveMessages(request):
                print(f"New message from {message.senderId}: {message.content}")
                # Add the message to chat history
                self.history.save_message(message)
                # Emit the new message to connected SocketIO clients
                socketio.emit('new_message', {
                    'sender': message.senderId,
                    'content': message.content,
                    'timestamp': message.timestamp
                })
        except grpc.RpcError as e:
            print(f"Error listening for messages: {e}")

    def check_active_users(self):
        """
        Periodically check for new users or users who have gone offline.
        Emit active users updates via SocketIO.
        """
        while self.is_running:
            try:
                request = pb2.ActiveUsersRequest()
                active_users_list = self.chat_stub.ActiveUsers(request)
                current_users = [user.uuid.uuid for user in active_users_list.users]

                # Find new users
                new_users = set(current_users) - set(self.active_users)
                if new_users:
                    print(f"New users found: {new_users}")
                    # Emit the new users to SocketIO clients
                    socketio.emit('new_users', {
                        'new_users': list(new_users)
                    })

                # Find offline users
                offline_users = set(self.active_users) - set(current_users)
                if offline_users:
                    print(f"Users offline: {offline_users}")
                    # Emit the offline users to SocketIO clients
                    socketio.emit('offline_users', {
                        'offline_users': list(offline_users)
                    })

                # Update the active users list
                self.active_users = current_users

            except grpc.RpcError as e:
                print(f"Error checking active users: {e}")
            
            # Check every 10 seconds (adjust as needed)
            sleep(10)

    def start(self):
        """
        Start the message listener and the user activity checker in separate threads.
        """
        print("Starting ChatManager...")
        # Start a thread to listen for incoming messages
        threading.Thread(target=self.listen_for_messages, daemon=True).start()

        # Start a thread to periodically check for active users
        threading.Thread(target=self.check_active_users, daemon=True).start()

    def stop(self):
        """
        Stop the chat manager from running.
        """
        self.is_running = False
        print("ChatManager stopped.")

import grpc
import threading
import asyncio
from time import time, sleep
import protos.kasugai_pb2 as pb2
import protos.kasugai_pb2_grpc as gpb2
from chat_history import ChatHistory
import const

class ChatManager:
    def __init__(self, server_address, user_id=1):
        self.channel = grpc.insecure_channel(server_address)
        self.chat_stub = gpb2.ChatServiceStub(self.channel)
        self.user_id = user_id  # User UUID
        self.active_users = []  # Keep track of active users
        self.message_queue = []
        self.is_running = True
        self.history = ChatHistory()
        self.register_client()

    # User registration
    def register_client(self):
        
        ack = self.chat_stub.RegisterClient(pb2.User(
            uuid=pb2.Id(uuid=const.CLIENT_ID),  # User now uses Id for uuid
            name=const.CLIENT_NAME
        ))
        print(f"Register Client: Success={ack.success}, Message={ack.message}")

    def send_message(self, content):
        try:
            message = pb2.Message(
                messageId=pb2.Id(uuid="message-" + str(time())),
                senderId=const.CLIENT_ID,
                recipientId='',
                content=content,
                timestamp=int(time())
            )
            ack = self.chat_stub.SendMessage(message)
            print(f"Send Message: Success={ack.success}, Message={ack.message}")
            # ChatHistory.add_message(const.CLIENT_ID, content, message.timestamp)
        except grpc.RpcError as e:
            print(f"Error sending message: {e}")

    def listen_for_messages(self):
        """
        Listen for incoming messages from the server and handle them.
        Emit new messages to the frontend via SocketIO.
        """
        try:
            request = pb2.Id(uuid=const.CLIENT_ID)
            message = self.chat_stub.ReceiveMessages(request)
            if message._state.response != None:
                # Add the message to chat history
                self.history.save_message(message)
                return message
            else:
                yield from asyncio.sleep(.1).__await__()
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
                    # socketio.emit('new_users', {
                    #     'new_users': list(new_users)
                    # })

                # Find offline users
                offline_users = set(self.active_users) - set(current_users)
                if offline_users:
                    print(f"Users offline: {offline_users}")
                    # Emit the offline users to SocketIO clients
                    # socketio.emit('offline_users', {
                    #     'offline_users': list(offline_users)
                    # })

                # Update the active users list
                self.active_users = current_users

            except grpc.RpcError as e:
                print(f"Error checking active users: {e}")
            
            # Check every 10 seconds (adjust as needed)
            sleep(10)

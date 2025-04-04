import grpc, uuid, time, threading, sys
from concurrent import futures
from google.protobuf.timestamp_pb2 import Timestamp
import kasugai_pb2 as pb
import kasugai_pb2_grpc as pb_grpc
from server_storage import ServerStorage
from auth_interceptor import AuthInterceptor
from server_logger import ServerLogger
from grpc_health.v1 import health_pb2_grpc
from health_service import HealthService

class UserService(pb_grpc.UserServiceServicer):
    def __init__(self, storage):
        self.logger = ServerLogger.get_logger("UserService")
        self.storage = storage

    def RegisterUser(self, request, context):
        try:
            user_id = str(uuid.uuid4())
            self.logger.info(f"Registering user: {request.name}")
            # Persist the user using our storage module
            self.server.add_user(user_id, request.name, request.status)
            user = pb.User(id=pb.Id(uuid=user_id), name=request.name, status=request.status)
            self.logger.info(f"User {user_id} registered successfully")
            return pb.Ack(success=True, message="User registered")
        except Exception as e:
            self.logger.error(f"Error in RegisterUser: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal error during user registration")
            return pb.Ack(success=False, message="Registration failed")

    def UpdateUserStatus(self, request, context):
        try:
            self.logger.info(f"Updating status for user {request.id.uuid} to {request.status}")
            self.server.update_user_status(request.id.uuid, request.status)
            self.logger.info(f"User {request.id.uuid} status updated successfully")
            return pb.Ack(success=True, message="Status updated")
        except Exception as e:
            self.logger.error(f"Error in UpdateUserStatus: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal error during status update")
            return pb.Ack(success=False, message="Status update failed")

    def GetUserList(self, request, context):
        try:
            self.logger.info("Fetching user list")
            users_data = self.server.list_users()
            # Convert tuples into pb.User objects
            users_list = []
            for uid, name, status in users_data:
                users_list.append(pb.User(id=pb.Id(uuid=uid), name=name, status=status))
            self.logger.info(f"Returning {len(users_list)} users")
            return pb.UserList(users=users_list)
        except Exception as e:
            self.logger.error(f"Error in GetUserList: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal error fetching user list")
            return pb.UserList()

    def GetUserById(self, request, context):
        try:
            self.logger.info(f"Fetching user with ID: {request.uuid}")
            user_record = self.server.get_user(request.uuid)
            if user_record:
                uid, name, status = user_record
                self.logger.info(f"User {uid} found")
                return pb.User(id=pb.Id(uuid=uid), name=name, status=status)
            else:
                self.logger.error(f"User {request.uuid} not found")
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details("User not found")
                return pb.User()
        except Exception as e:
            self.logger.error(f"Error in GetUserById: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal error fetching user")
            return pb.User()

class RoomService(pb_grpc.RoomServiceServicer):
    def __init__(self, storage):
        self.logger = ServerLogger.get_logger("RoomService")
        self.storage = storage
        # In-memory dictionary to hold immediate message queues per room.
        self.room_messages = {}
        # Lock to protect access to the room_messages dictionary.
        self.room_lock = threading.Lock()

    def CreateRoom(self, request, context):
        try:
            room_id = str(uuid.uuid4())
            participant_ids = [pid.uuid for pid in request.participantIds]
            self.logger.info(f"Creating room '{request.name}' with creator {request.creatorId.uuid}")
            self.storage.add_room(room_id, request.name, participant_ids, request.type, request.creatorId.uuid, request.password)
            # Protect assignment with a lock.
            with self.room_lock:
                self.room_messages[room_id] = []
            self.logger.info(f"Room {room_id} created successfully")
            return pb.Ack(success=True, message=room_id)
        except Exception as e:
            self.logger.error(f"Error in CreateRoom: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal error creating room")
            return pb.Ack(success=False, message="Room creation failed")

    def JoinRoom(self, request, context):
        try:
            room_id = request.roomId.uuid
            self.logger.info(f"User attempting to join room {room_id}")
            room = self.storage.get_room(room_id)
            if room:
                self.logger.info(f"User joined room {room_id}")
                return pb.Ack(success=True, message=f"Joined room {room_id}")
            else:
                self.logger.error(f"Room {room_id} not found")
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details("Room not found")
                return pb.Ack(success=False, message="Room not found")
        except Exception as e:
            self.logger.error(f"Error in JoinRoom: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal error joining room")
            return pb.Ack(success=False, message="Join room failed")

    def LeaveRoom(self, request, context):
        try:
            room_id = request.uuid
            self.logger.info(f"User leaving room {room_id}")
            # Here you can add logic to update participants, if needed.
            self.logger.info(f"User left room {room_id}")
            return pb.Ack(success=True, message="Left room")
        except Exception as e:
            self.logger.error(f"Error in LeaveRoom: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal error leaving room")
            return pb.Ack(success=False, message="Leave room failed")

    def GetRoomParticipants(self, request, context):
        try:
            room_id = request.uuid
            self.logger.info(f"Fetching participants for room {room_id}")
            room = self.storage.get_room(room_id)
            if room:
                participant_ids = room['participant_ids']
                participants = []
                for uid in participant_ids:
                    user_record = self.storage.get_user(uid)
                    if user_record:
                        uid, name, status = user_record
                        participants.append(pb.User(id=pb.Id(uuid=uid), name=name, status=status))
                self.logger.info(f"Found {len(participants)} participants in room {room_id}")
                return pb.RoomParticipants(roomId=pb.Id(uuid=room_id), participants=participants)
            else:
                self.logger.error(f"Room {room_id} not found")
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details("Room not found")
                return pb.RoomParticipants()
        except Exception as e:
            self.logger.error(f"Error in GetRoomParticipants: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal error fetching room participants")
            return pb.RoomParticipants()

class ChatService(pb_grpc.ChatServiceServicer):
    def __init__(self, storage):
        self.logger = ServerLogger.get_logger("ChatService")
        self.storage = storage
        # In-memory dictionary to queue messages per room.
        self.room_messages = {}
        # Lock to protect access to room_messages.
        self.msg_lock = threading.Lock()

    def SendTextMessage(self, request, context):
        try:
            room_id = request.recipientId.uuid
            self.logger.info(f"Received message from {request.senderId.uuid} for room {room_id}")
            now = Timestamp()
            now.GetCurrentTime()
            request.timestamp.CopyFrom(now)
            message_id = request.id.uuid if request.id.uuid else str(uuid.uuid4())
            self.storage.add_message(message_id, room_id, request.senderId.uuid, request.content, now.ToJsonString())
            with self.msg_lock:
                if room_id not in self.room_messages:
                    self.room_messages[room_id] = []
                self.room_messages[room_id].append(request)
            self.logger.info("Message stored and queued for streaming successfully")
            return pb.Ack(success=True, message="Message sent")
        except Exception as e:
            self.logger.error(f"Error in SendTextMessage: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal error sending message")
            return pb.Ack(success=False, message="Message failed")

    def ReceiveTextMessages(self, request, context):
        try:
            room_id = request.uuid
            self.logger.info(f"Streaming messages for room {room_id}")
            # Copy the messages under lock so the lock isn't held during streaming.
            with self.msg_lock:
                messages = list(self.room_messages.get(room_id, []))
            for message in messages:
                yield message
                time.sleep(0.1)
        except Exception as e:
            self.logger.error(f"Error in ReceiveTextMessages: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal error streaming messages")

logger = ServerLogger.get_logger("KasugaiServer")

def command_listener(server):
    """
    Listens for console commands to shutdown or restart the server.
    """
    while True:
        cmd = input("Enter command (shutdown/restart): ").strip().lower()
        if cmd == "shutdown":
            logger.info("Shutdown command received. Shutting down server gracefully.")
            # Stop the server immediately (0 seconds grace period)
            server.stop(0)
            sys.exit(0)
        elif cmd == "restart":
            logger.info("Restart command received. Restarting server.")
            # Stop the server and then restart after a short delay
            server.stop(0)
            time.sleep(1)
            # Note: In this simple example, we call serve() recursively.
            # In a production system, consider using an external process manager.
            serve()
            break

def serve():
    
    logger.info("Starting Kasugai gRPC server...")
    # Instantiate persistent storage.
    storage = ServerStorage()
    # Create the authentication interceptor.
    auth_interceptor = AuthInterceptor(valid_token="my-secret-token")
    # Create the gRPC server with the interceptor.
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10),
                         interceptors=[auth_interceptor])
    logger.info("gRPC server created with authentication interceptor")

    # Instantiate services.
    user_service = UserService(storage)
    room_service = RoomService(storage)
    chat_service = ChatService(storage)
    health_service = HealthService()
    
    # Register services.
    pb_grpc.add_UserServiceServicer_to_server(user_service, server)
    pb_grpc.add_RoomServiceServicer_to_server(room_service, server)
    pb_grpc.add_ChatServiceServicer_to_server(chat_service, server)
    # Register the health service.
    health_pb2_grpc.add_HealthServicer_to_server(health_service, server)
    
    # Load TLS credentials (if using TLS; see previous improvements) or choose insecure port.
    server.add_insecure_port('[::]:8008')
    logger.info("Kasugai gRPC server started on port 8008")
    server.start()
    server.wait_for_termination()
    logger.info("Kasugai gRPC server terminated")

if __name__ == '__main__':
    serve()
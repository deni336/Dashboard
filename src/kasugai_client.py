import grpc
from src.global_logger import GlobalLogger
from kasugai_server.python.kasugai_pb2 import Id, Room, TextMessage, MediaStream, MediaType, User, UserStatus, JoinRoomRequest
from kasugai_server.python.kasugai_pb2_grpc import (
    UserServiceStub, RoomServiceStub, ChatServiceStub,
    MediaServiceStub, FileTransferServiceStub
)
from google.protobuf.timestamp_pb2 import Timestamp
import uuid

class KasugaiClient:
    def __init__(self, host='localhost', port=8008):
        self.logger = GlobalLogger.get_logger('KasugaiClient')
        self.channel = grpc.insecure_channel(f'{host}:{port}')
        self.user_stub = UserServiceStub(self.channel)
        self.room_stub = RoomServiceStub(self.channel)
        self.chat_stub = ChatServiceStub(self.channel)
        self.media_stub = MediaServiceStub(self.channel)
        self.file_stub = FileTransferServiceStub(self.channel)

        self.current_user = None
        self.current_room_id = None

    # ===== User Logic =====
    def register_user(self, name):
        user = User(
            id=Id(uuid=str(uuid.uuid4())),
            name=name,
            status=UserStatus.ONLINE
        )
        try:
            response = self.user_stub.RegisterUser(user)
            if response.success:
                self.user_stub.UpdateUserStatus(user)
                self.current_user = user
                return user
            else:
                raise Exception(f"RegisterUser failed: {response.message}")
        except Exception as e:
            self.logger.error(f"register_user error: {e}")
            raise

    # ===== Room Logic =====
    def create_room(self, name, password, room_type, creator_id):
        try:
            room = Room(
                name=name,
                type=room_type,
                creatorId=Id(uuid=creator_id)
            )
            response = self.room_stub.CreateRoom(room)
            if response.success:
                return Id(uuid=response.message)
            raise Exception(f"CreateRoom failed: {response.message}")
        except Exception as e:
            self.logger.error(f"create_room error: {e}")
            raise


    def join_room(self, room_id, password=''):
        try:
            if not isinstance(room_id.uuid, str):
                raise ValueError("room_id must be a string UUID")
            if not isinstance(password, str):
                raise ValueError("password must be a string")

            request = JoinRoomRequest(
                roomId=Id(uuid=room_id.uuid),
                password=password
            )
            response = self.room_stub.JoinRoom(request)
            if response.success:
                self.current_room_id = room_id
            return response
        except Exception as e:
            self.logger.error(f"join_room error: {e}")
            raise



    # ===== Chat Logic =====
    def send_text_message(self, content):
        if not self.current_user or not self.current_room_id:
            raise ValueError("Not registered or not in a room")

        message = TextMessage(
            id=Id(uuid=str(uuid.uuid4())),
            senderId=self.current_user.id,
            recipientId=Id(uuid=self.current_room_id),
            content=content,
            timestamp=Timestamp()
        )
        return self.chat_stub.SendTextMessage(message)

    def receive_text_messages(self):
        if not self.current_user or not self.current_room_id:
            raise ValueError("Not registered or not in a room")
        metadata = (('user', self.current_user.id.uuid),)
        return self.chat_stub.ReceiveTextMessages(Id(uuid=self.current_room_id), metadata=metadata)

    # ===== Media Logic =====
    def start_screen_share(self):
        return self.media_stub.StartMediaStream(iter([
            MediaStream(
                id=Id(uuid=self.current_room_id),
                senderId=self.current_user.id,
                type=MediaType.SCREEN
            )
        ]))

    def end_screen_share(self):
        return self.media_stub.EndMediaStream(Id(uuid=self.current_room_id))

    def close(self):
        self.channel.close()

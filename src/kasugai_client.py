import grpc
import uuid
from google.protobuf.empty_pb2 import Empty
from google.protobuf.timestamp_pb2 import Timestamp
from protos.kasugai_pb2 import *
from protos.kasugai_pb2_grpc import *
import traceback

class UserServiceClient:
    def __init__(self, channel):
        self.stub = UserServiceStub(channel)

    def register_user(self, name) -> User:
        user = User(
            id=Id(uuid=str(uuid.uuid4())),
            name=name,
            status=UserStatus.ONLINE
        )
        response = self.stub.RegisterUser(user)
        print(f"RegisterUser response: {response}")
        if response.success:
            return user
        else:
            raise ValueError(f"Failed to register user: {response.message}")

    def update_user_status(self, user):
        return self.stub.UpdateUserStatus(user)

    def get_user_list(self):
        return self.stub.GetUserList(Empty())

    def get_user_by_id(self, user_id):
        return self.stub.GetUserById(Id(uuid=user_id))

class RoomServiceClient:
    def __init__(self, channel):
        self.stub = RoomServiceStub(channel)

    def create_room(self, name, room_type, creator_id):
        room = Room(
            name=name,
            type=room_type,
            creatorId=creator_id
        )
        return self.stub.CreateRoom(room)

    def join_room(self, room_id, user_id):
        metadata = (('user', user_id),)
        return self.stub.JoinRoom(Id(uuid=room_id), metadata=metadata)

    def leave_room(self, room_id, user_id):
        metadata = (('user', user_id),)
        return self.stub.LeaveRoom(Id(uuid=room_id), metadata=metadata)

    def get_room_participants(self, room_id):
        return self.stub.GetRoomParticipants(Id(uuid=room_id))

class ChatServiceClient:
    def __init__(self, channel):
        self.stub = ChatServiceStub(channel)

    def send_text_message(self, sender_id, recipient_id, content):
        message = TextMessage(
            id=Id(uuid=str(uuid.uuid4())),
            senderId=Id(uuid=sender_id),
            recipientId=Id(uuid=recipient_id),
            content=content,
            timestamp=Timestamp()
        )
        return self.stub.SendTextMessage(message)

    def receive_text_messages(self, room_id, user_id):
        metadata = (('user', user_id),)
        return self.stub.ReceiveTextMessages(Id(uuid=room_id), metadata=metadata)

class MediaServiceClient:
    def __init__(self, channel):
        self.stub = MediaServiceStub(channel)

    def start_media_stream(self, room_id, sender_id, media_type):
        def stream_generator():
            yield MediaStream(
                id=Id(uuid=room_id),
                senderId=Id(uuid=sender_id),
                type=media_type
            )
            # Add logic here to continuously yield MediaStream objects

        return self.stub.StartMediaStream(stream_generator())

    def end_media_stream(self, stream_id):
        return self.stub.EndMediaStream(Id(uuid=stream_id))

    def manage_voip_call(self):
        return self.stub.ManageVoIPCall()

class FileTransferServiceClient:
    def __init__(self, channel):
        self.stub = FileTransferServiceStub(channel)

    def initiate_file_transfer(self, file_metadata):
        return self.stub.InitiateFileTransfer(file_metadata)

    def transfer_file_chunk(self):
        return self.stub.TransferFileChunk()

    def receive_file_metadata(self, file_id):
        return self.stub.ReceiveFileMetadata(Id(uuid=file_id))

    def receive_file_chunks(self, file_id):
        return self.stub.ReceiveFileChunks(Id(uuid=file_id))

class KasugaiClient:
    def __init__(self, host='localhost', port=8008):
        self.channel = grpc.insecure_channel(f'{host}:{port}')
        self.user_service = UserServiceClient(self.channel)
        self.room_service = RoomServiceClient(self.channel)
        self.chat_service = ChatServiceClient(self.channel)
        self.media_service = MediaServiceClient(self.channel)
        self.file_transfer_service = FileTransferServiceClient(self.channel)
        self.current_user = None
        self.current_room_id = None

    def close(self):
        self.channel.close()

    def register_user(self, name):
        if self.current_user is None:
            self.current_user = self.user_service.register_user(name)
            return self.current_user
        else:
            print(f"User already registered: {self.current_user.name}")
            return self.current_user

    def create_room(self, name, room_type):
        if self.current_user is None:
            raise ValueError("User not registered")
        response = self.room_service.create_room(name, room_type, self.current_user.id)
        if response.success:
            return Id(uuid=response.message)  # Return the room ID
        else:
            raise ValueError(f"Failed to create room: {response.message}")

    def join_room(self, room_id):
        if not self.current_user:
            raise ValueError("User not registered")
        response = self.room_service.join_room(room_id.uuid, self.current_user.id.uuid)
        if response.success:
            self.current_room_id = room_id.uuid
        return response

    def leave_room(self):
        if not self.current_user or not self.current_room_id:
            raise ValueError("User not registered or not in a room")
        response = self.room_service.leave_room(self.current_room_id, self.current_user.id.uuid)
        if response.success:
            self.current_room_id = None
        return response

    def send_text_message(self, content):
        if not self.current_user or not self.current_room_id:
            raise ValueError("User not registered or not in a room")
        response = self.chat_service.send_text_message(self.current_user.id.uuid, self.current_room_id, content)
        print(f"Message sent: {response.success}, {response.message}")
        return response

    def receive_text_messages(self):
        if not self.current_user or not self.current_room_id:
            raise ValueError("User not registered or not in a room")
        return self.chat_service.receive_text_messages(self.current_room_id, self.current_user.id.uuid)

    def start_screen_share(self):
        if not self.current_user or not self.current_room_id:
            raise ValueError("User not registered or not in a room")
        return self.media_service.start_media_stream(self.current_room_id, self.current_user.id.uuid, MediaType.SCREEN)

    def end_screen_share(self):
        if not self.current_user or not self.current_room_id:
            raise ValueError("User not registered or not in a room")
        return self.media_service.end_media_stream(self.current_room_id)

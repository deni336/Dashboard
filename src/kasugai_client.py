import grpc
import uuid
from google.protobuf.empty_pb2 import Empty
from google.protobuf.timestamp_pb2 import Timestamp
from protos.kasugai_pb2 import *
from protos.kasugai_pb2_grpc import *
import traceback

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
            return kasugai__pb2.Id(uuid=response.message)  # Return the room ID
        else:
            raise ValueError(f"Failed to create room: {response.message}")

    def join_room(self, room_id, password):
        if not self.current_user:
            raise ValueError("User not registered")
        response = self.room_service.join_room(room_id.uuid, password, self.current_user.id.uuid)
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
        return self.media_service.start_media_stream(self.current_room_id, self.current_user.id.uuid, kasugai__pb2.MediaType.SCREEN)

    def end_screen_share(self):
        if not self.current_user or not self.current_room_id:
            raise ValueError("User not registered or not in a room")
        return self.media_service.end_media_stream(self.current_room_id)

class UserServiceClient:
    def __init__(self, channel):
        self.stub = UserServiceStub(channel)

    def register_user(self, name):
        self.user = kasugai__pb2.User(
            id = kasugai__pb2.Id(uuid=str(uuid.uuid4())),
            name = name,
            status = kasugai__pb2.UserStatus.ONLINE
        )
        response = self.stub.RegisterUser(self.user)
        print(f"RegisterUser response: {response}")
        if response.success:
            self.update_user_status()
            return self.user
        else:
            raise ValueError(f"Failed to register user: {response.message}")

    def update_user_status(self):
        return self.stub.UpdateUserStatus(self.user)

    def get_user_list(self):
        return self.stub.GetUserList(Empty())

    def get_user_by_id(self, user_id):
        return self.stub.GetUserById(kasugai__pb2.Id(uuid=user_id))

class RoomServiceClient:
    def __init__(self, channel):
        self.stub = RoomServiceStub(channel)

    def create_room(self, name, password, room_type, creator_id):
        room = kasugai__pb2.Room(
            name=name,
            password=password,
            type=room_type,
            creatorId=creator_id
        )
        return self.stub.CreateRoom(room)

    def join_room(self, room_id, password, user_id):
        metadata = (('user', user_id), ('password', password))
        return self.stub.JoinRoom(kasugai__pb2.Id(uuid=room_id), metadata=metadata)

    def leave_room(self, room_id, user_id):
        metadata = (('user', user_id),)
        return self.stub.LeaveRoom(kasugai__pb2.Id(uuid=room_id), metadata=metadata)

    def get_room_participants(self, room_id):
        return self.stub.GetRoomParticipants(kasugai__pb2.Id(uuid=room_id))

class ChatServiceClient:
    def __init__(self, channel):
        self.stub = ChatServiceStub(channel)

    def send_text_message(self, sender_id, recipient_id, content):
        message = kasugai__pb2.TextMessage(
            id = kasugai__pb2.Id(uuid=str(uuid.uuid4())),
            senderId = kasugai__pb2.Id(uuid=sender_id),
            recipientId = kasugai__pb2.Id(uuid=recipient_id),
            content = content,
            timestamp = Timestamp()
        )
        return self.stub.SendTextMessage(message)

    def receive_text_messages(self, room_id, user_id):
        metadata = (('user', user_id),)
        return self.stub.ReceiveTextMessages(kasugai__pb2.Id(uuid=room_id), metadata=metadata)

class MediaServiceClient:
    def __init__(self, channel):
        self.stub = MediaServiceStub(channel)

    def start_media_stream(self, room_id, sender_id, media_type):
        def stream_generator():
            yield kasugai__pb2.MediaStream(
                id = kasugai__pb2.Id(uuid=room_id),
                senderId = kasugai__pb2.Id(uuid=sender_id),
                type=media_type
            )
            # Add logic here to continuously yield MediaStream objects

        return self.stub.StartMediaStream(stream_generator())

    def end_media_stream(self, stream_id):
        return self.stub.EndMediaStream(kasugai__pb2.Id(uuid=stream_id))

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
        return self.stub.ReceiveFileMetadata(kasugai__pb2.Id(uuid=file_id))

    def receive_file_chunks(self, file_id):
        return self.stub.ReceiveFileChunks(kasugai__pb2.Id(uuid=file_id))


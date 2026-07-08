import grpc
import os
import hashlib
import queue
import threading
from src.global_logger import GlobalLogger
from kasugai_server.python.kasugai_pb2 import Id, Room, TextMessage, MediaStream, MediaType, User, UserStatus, FileMetadata, FileChunk
from kasugai_server.python.kasugai_pb2_grpc import UserServiceStub, RoomServiceStub, ChatServiceStub, MediaServiceStub, FileTransferServiceStub
from google.protobuf.timestamp_pb2 import Timestamp
import uuid


class MediaChannel:
    """
    Handle for an open bidirectional StartMediaStream connection: send_frame()
    broadcasts this user's own captured frames (e.g. while screen-sharing) to
    the rest of the room, while incoming frames from other participants are
    delivered to the on_frame callback passed to start_media_channel().
    """
    def __init__(self, call, send_queue, room_id, sender_id):
        self._call = call
        self._send_queue = send_queue
        self._room_id = room_id
        self._sender_id = sender_id
        self._closed = False

    def send_frame(self, data):
        if self._closed:
            return False

        frame = MediaStream(
            id=Id(uuid=self._room_id),
            senderId=Id(uuid=self._sender_id),
            type=MediaType.SCREEN,
            data=data,
            timestamp=self._timestamp()
        )

        # Screen-share frames are disposable. If the gRPC sender is backed up,
        # discard older queued frames so viewers see the freshest available one.
        if self._send_queue.full():
            try:
                self._send_queue.get_nowait()
            except queue.Empty:
                pass

        try:
            self._send_queue.put_nowait(frame)
            return True
        except queue.Full:
            return False

    def close(self):
        if self._closed:
            return
        self._closed = True
        while True:
            try:
                self._send_queue.get_nowait()
            except queue.Empty:
                break
        self._send_queue.put(None)
        self._call.cancel()

    @staticmethod
    def _timestamp():
        timestamp = Timestamp()
        timestamp.GetCurrentTime()
        return timestamp

class KasugaiClient:
    def __init__(self, host='localhost', port=8008, file_transfer_host=None, file_transfer_port=50051,
                 media_host=None, media_port=50052):
        self.logger = GlobalLogger.get_logger('KasugaiClient')
        self.channel = grpc.insecure_channel(f'{host}:{port}')
        self.user_stub = UserServiceStub(self.channel)
        self.room_stub = RoomServiceStub(self.channel)
        self.chat_stub = ChatServiceStub(self.channel)

        # FileTransferService and MediaService each run as their own gRPC
        # server (see kasugai_server/main.go), so they need their own channels
        # rather than reusing the chat channel/port.
        self.file_channel = grpc.insecure_channel(f'{file_transfer_host or host}:{file_transfer_port}')
        self.file_stub = FileTransferServiceStub(self.file_channel)

        self.media_grpc_channel = grpc.insecure_channel(f'{media_host or host}:{media_port}')
        self.media_stub = MediaServiceStub(self.media_grpc_channel)

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
                creatorId=Id(uuid=creator_id),
                password=password
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
            if not self.current_user:
                raise ValueError("Not registered")

            # The server reads the joining user's ID and the room's password
            # from request metadata rather than the request body. A passwordless
            # room's key is stored server-side as the literal string "OPEN"
            # (see RoomBuilder.WithKey), so an empty password must match that.
            metadata = (('user', self.current_user.id.uuid), ('key', password or 'OPEN'))
            response = self.room_stub.JoinRoom(Id(uuid=room_id.uuid), metadata=metadata)
            if response.success:
                self.current_room_id = room_id.uuid
            return response
        except Exception as e:
            self.logger.error(f"join_room error: {e}")
            raise

    def get_room_participants(self, room_id):
        try:
            response = self.room_stub.GetRoomParticipants(Id(uuid=room_id))
            return list(response.participants)
        except Exception as e:
            self.logger.error(f"get_room_participants error: {e}")
            raise

    # ===== Chat Logic =====
    def send_text_message(self, content):
        if not self.current_user or not self.current_room_id:
            raise ValueError("Not registered or not in a room")

        timestamp = Timestamp()
        timestamp.GetCurrentTime()
        message = TextMessage(
            id=Id(uuid=str(uuid.uuid4())),
            senderId=self.current_user.id,
            recipientId=Id(uuid=self.current_room_id),
            content=content,
            timestamp=timestamp
        )
        return self.chat_stub.SendTextMessage(message)

    def receive_text_messages(self, room_id=None):
        """
        Stream incoming TextMessage objects as they arrive.
        """
        if not self.current_user or not self.current_room_id:
            raise ValueError("Not registered or not in a room")
        metadata = (('user', self.current_user.id.uuid),)
        return self.chat_stub.ReceiveTextMessages(Id(uuid=room_id or self.current_room_id), metadata=metadata)

    # ===== Media Logic =====
    def start_media_channel(self, on_frame=None):
        """
        Open a persistent bidi MediaStream channel for the current room. This
        registers the caller with the server so any frames another
        participant broadcasts (e.g. a screen share) get delivered here via
        on_frame. Returns a MediaChannel that can also be used to broadcast
        this user's own captured frames.
        """
        if not self.current_user or not self.current_room_id:
            raise ValueError("Not registered or not in a room")

        room_id = self.current_room_id
        sender_id = self.current_user.id.uuid
        send_queue = queue.Queue(maxsize=2)

        def request_generator():
            # Pure registration message so the server knows which room/user
            # this stream belongs to; carries no frame data.
            yield MediaStream(
                id=Id(uuid=room_id),
                senderId=Id(uuid=sender_id),
                type=MediaType.SCREEN,
                data=b'',
                timestamp=MediaChannel._timestamp()
            )
            while True:
                item = send_queue.get()
                if item is None:
                    return
                yield item

        call = self.media_stub.StartMediaStream(request_generator())

        def listen():
            try:
                for frame in call:
                    if on_frame:
                        on_frame(frame)
            except grpc.RpcError as e:
                self.logger.info(f"Media channel closed: {e.code()}")

        threading.Thread(target=listen, daemon=True).start()
        return MediaChannel(call, send_queue, room_id, sender_id)

    # ===== File Transfer Logic =====
    FILE_CHUNK_SIZE = 64 * 1024

    def upload_file(self, file_path, sender_id, recipient_id, mime_type='application/octet-stream'):
        """
        Register file metadata and stream the file's bytes to the server in
        chunks, tagged with sender/recipient. Returns the generated file_id.
        """
        file_id = str(uuid.uuid4())
        name = os.path.basename(file_path)
        size = os.path.getsize(file_path)

        metadata = FileMetadata(
            id=Id(uuid=file_id),
            name=name,
            size=size,
            mimeType=mime_type,
            senderId=Id(uuid=sender_id),
            recipientId=Id(uuid=recipient_id),
        )

        def chunk_iter():
            chunk_number = 0
            with open(file_path, 'rb') as f:
                if size == 0:
                    yield FileChunk(
                        fileId=Id(uuid=file_id),
                        data=b'',
                        chunkNumber=0,
                        isLastChunk=True,
                        checksum=hashlib.sha256(b'').hexdigest(),
                    )
                    return

                while True:
                    data = f.read(self.FILE_CHUNK_SIZE)
                    if not data:
                        break
                    yield FileChunk(
                        fileId=Id(uuid=file_id),
                        data=data,
                        chunkNumber=chunk_number,
                        isLastChunk=f.tell() >= size,
                        checksum=hashlib.sha256(data).hexdigest(),
                    )
                    chunk_number += 1

        try:
            ack = self.file_stub.InitiateFileTransfer(metadata)
            if not ack.success:
                raise Exception(f"InitiateFileTransfer failed: {ack.message}")

            ack = self.file_stub.TransferFileChunk(chunk_iter())
            if not ack.success:
                raise Exception(f"TransferFileChunk failed: {ack.message}")

            return file_id
        except Exception as e:
            self.logger.error(f"upload_file error: {e}")
            raise

    def get_file_metadata(self, file_id):
        try:
            return self.file_stub.ReceiveFileMetadata(Id(uuid=file_id))
        except Exception as e:
            self.logger.error(f"get_file_metadata error: {e}")
            raise

    def download_file(self, file_id, destination_dir=None, destination_path=None, metadata=None):
        """
        Fetch a file's metadata and stream its chunks from the server,
        writing them to destination_path or destination_dir. Returns the path
        of the saved file.
        """
        try:
            metadata = metadata or self.get_file_metadata(file_id)
            if destination_path is None:
                if destination_dir is None:
                    raise ValueError("destination_dir or destination_path is required")
                destination_path = os.path.join(destination_dir, metadata.name or file_id)

            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            with open(destination_path, 'wb') as f:
                for chunk in self.file_stub.ReceiveFileChunks(Id(uuid=file_id)):
                    if chunk.checksum and hashlib.sha256(chunk.data).hexdigest() != chunk.checksum:
                        raise ValueError(f"Checksum mismatch on chunk {chunk.chunkNumber} for file {file_id}")
                    f.write(chunk.data)
                    if chunk.isLastChunk:
                        break
            return destination_path
        except Exception as e:
            self.logger.error(f"download_file error: {e}")
            raise

    def close(self):
        self.channel.close()
        self.file_channel.close()
        self.media_grpc_channel.close()

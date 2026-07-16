import base64
import datetime
import grpc
import json
import threading
import time
import traceback
from flask_socketio import SocketIO
from src.global_logger import GlobalLogger
from src.config_handler import ConfigHandler
from src.db_handler import ChatHistory
from src.kasugai_client import KasugaiClient
from kasugai_server.python.kasugai_pb2 import Id, RoomType
from src.message_processor import MessageProcessor

class ChatManager:
    def __init__(self, app, user_name, batch_size=10, flush_interval=1.0):
        self.logger = GlobalLogger.get_logger('ChatManager')
        self.config = ConfigHandler()
        self.chat_history = ChatHistory()
        # Setup SocketIO. Waitress is a synchronous WSGI server with no raw-socket
        # hijacking support, so it cannot serve WebSocket upgrades -- restrict to
        # long-polling, which is all "threading" async_mode actually supports here.
        self.socketio = SocketIO(app, async_mode='threading', transports=['polling'])
        # Initialize gRPC client
        self.client = KasugaiClient(
            host=self.config.get('WebServer', 'kasaddress'),
            port=self.config.get('WebServer', 'kasport'),
            media_port=self.config.getint('WebServer', 'mediaport')
        )
        # Initialize message processor for batching and persistence
        self.processor = MessageProcessor(
            self.socketio,
            self.chat_history,
            batch_size=batch_size,
            flush_interval=flush_interval,
            on_message=self._handle_incoming_message
        )

        self.current_room = None
        self.media_channel = None
        self._message_listener_thread = None
        self._message_stream = None
        self._listener_generation = 0
        self._listener_lock = threading.Lock()
        self._file_offer_lock = threading.Lock()
        self._pending_file_offers = {}
        self.user = self.register_user(user_name)

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
            if response.success:
                self.current_room = room_id.uuid
                self.start_batch_listening()
                self.start_media_channel()

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
            response = self.client.join_room(Id(uuid=room_name), password)
            self.logger.info(f"Joined room: {response.success}, {response.message}")
            if response.success:
                self.current_room = room_name
                # Start listening for batched messages
                self.start_batch_listening()
                self.start_media_channel()
            return bool(response.success)
        except Exception as e:
            self.logger.error(f"Failed to join room: {e}")
            return False

    def send_message(self, content):
        try:
            response = self.client.send_text_message(content)
            self.logger.info(f"Send Message: Success={response.success}, Message={response.message}")
            return bool(response.success)
        except grpc.RpcError as e:
            self.logger.error(f"gRPC Error sending message: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error sending message: {str(e)}")
        return False

    def list_participants(self):
        """
        Return the other users (excluding self) currently in the active room.
        """
        if not self.current_room:
            return []
        try:
            participants = self.client.get_room_participants(self.current_room)
            return [
                {"id": p.id.uuid, "name": p.name}
                for p in participants
                if p.id.uuid != self.user.id.uuid
            ]
        except Exception as e:
            self.logger.error(f"Failed to list participants: {e}")
            return []

    def send_file_offer(self, recipient_id, file_id, filename, size, mime_type='application/octet-stream'):
        """
        Notify a specific room member that a file is available for them to
        download, by broadcasting a tagged message through the existing chat
        channel. Every client in the room receives it, but only the intended
        recipient's UI acts on it.
        """
        content = json.dumps({
            "type": "file_offer",
            "fileId": file_id,
            "name": filename,
            "size": size,
            "mimeType": mime_type,
            "senderId": self.user.id.uuid,
            "senderName": self.user.name,
            "recipientId": recipient_id,
            "createdAt": datetime.datetime.utcnow().isoformat(timespec='seconds') + "Z",
        })
        self.send_message(content)

    def _handle_incoming_message(self, message):
        try:
            payload = json.loads(message.content)
        except (TypeError, json.JSONDecodeError):
            return

        if not isinstance(payload, dict) or payload.get("type") != "file_offer":
            return
        if not self.user or payload.get("recipientId") != self.user.id.uuid:
            return

        file_id = payload.get("fileId")
        if not file_id:
            return

        offer = {
            "fileId": file_id,
            "name": payload.get("name") or file_id,
            "size": int(payload.get("size") or 0),
            "mimeType": payload.get("mimeType") or "application/octet-stream",
            "senderId": payload.get("senderId") or "",
            "senderName": payload.get("senderName") or "Unknown",
            "recipientId": payload.get("recipientId") or "",
            "createdAt": payload.get("createdAt") or "",
            "downloaded": False,
        }
        with self._file_offer_lock:
            current = self._pending_file_offers.get(file_id, {})
            offer["downloaded"] = bool(current.get("downloaded", False))
            self._pending_file_offers[file_id] = offer

    def get_pending_file_offers(self):
        with self._file_offer_lock:
            return list(self._pending_file_offers.values())

    def mark_file_offer_downloaded(self, file_id):
        with self._file_offer_lock:
            offer = self._pending_file_offers.get(file_id)
            if offer:
                offer["downloaded"] = True

    def start_media_channel(self):
        """
        Join this room's screen-share channel. Every room member does this on
        entering the room, so whoever is sharing their screen broadcasts to
        everyone automatically -- no separate "watch" step needed.
        """
        try:
            if self.media_channel:
                self.media_channel.close()
            self.media_channel = self.client.start_media_channel(on_frame=self._on_media_frame)
        except Exception as e:
            self.logger.error(f"Failed to start media channel: {e}")

    def _on_media_frame(self, frame):
        if not frame.data:
            self.socketio.emit('screen_share_stopped', {'sender': frame.senderId.uuid})
            return
        self.socketio.emit('screen_frame', {
            'sender': frame.senderId.uuid,
            'data': base64.b64encode(frame.data).decode('ascii'),
        })

    def send_screen_frame(self, data):
        if not self.media_channel:
            raise ValueError("Media channel not started -- not in a room yet")
        if not self.media_channel.send_frame(data):
            self.logger.debug("Dropped screen frame because media queue is full")

    def stop_screen_sharing(self):
        """
        Signal that this user stopped sharing. The media channel itself stays
        open afterward since it's also how this user keeps watching others.
        """
        if self.media_channel:
            self.media_channel.send_frame(b'')

    def start_batch_listening(self):
        if not self.current_room:
            return

        with self._listener_lock:
            self._listener_generation += 1
            generation = self._listener_generation
            room_id = self.current_room
            if self._message_stream:
                self._message_stream.cancel()

        listener_thread = threading.Thread(
            target=self.batch_listen_for_messages,
            args=(room_id, generation),
            daemon=True
        )
        self._message_listener_thread = listener_thread
        listener_thread.start()

    def _is_active_listener(self, generation):
        with self._listener_lock:
            return generation == self._listener_generation

    def batch_listen_for_messages(self, room_id, generation):
        """
        Listens to incoming messages and enqueues them to the processor, which
        does its own timeout-based batching (see MessageProcessor). Messages
        must be forwarded one at a time as they arrive here -- gating on
        accumulating a fixed batch size at the stream level means a message
        would never be delivered at all until enough others happened to
        arrive alongside it.
        """
        while self._is_active_listener(generation):
            try:
                stream = self.client.receive_text_messages(room_id=room_id)
                with self._listener_lock:
                    if generation != self._listener_generation:
                        stream.cancel()
                        return
                    self._message_stream = stream

                for message in stream:
                    if not self._is_active_listener(generation):
                        return
                    self.logger.info(f"Queued message from {message.senderId.uuid}")
                    self.processor.enqueue(message)
            except grpc.RpcError as e:
                if not self._is_active_listener(generation) or e.code() == grpc.StatusCode.CANCELLED:
                    return
                self.logger.error(f"gRPC stream error: {e.code()}: {e.details()}")
            except Exception as e:
                if not self._is_active_listener(generation):
                    return
                self.logger.error(f"Unexpected error in batch receive: {str(e)}")
                self.logger.error(traceback.format_exc())
            finally:
                with self._listener_lock:
                    if generation == self._listener_generation:
                        self._message_stream = None

            time.sleep(1)

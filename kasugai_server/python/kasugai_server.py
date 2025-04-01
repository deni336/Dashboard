import grpc
from concurrent import futures
import time
import uuid
from google.protobuf.timestamp_pb2 import Timestamp
import kasugai_pb2 as pb
import kasugai_pb2_grpc as pb_grpc

users = {}
rooms = {}
room_messages = {}

class UserService(pb_grpc.UserServiceServicer):
    def RegisterUser(self, request, context):
        user_id = str(uuid.uuid4())
        user = pb.User(id=pb.Id(uuid=user_id), name=request.name, status=request.status)
        users[user_id] = user
        return pb.Ack(success=True, message="User registered")

    def UpdateUserStatus(self, request, context):
        if request.id.uuid in users:
            users[request.id.uuid].status = request.status
            return pb.Ack(success=True, message="Status updated")
        return pb.Ack(success=False, message="User not found")

    def GetUserList(self, request, context):
        return pb.UserList(users=list(users.values()))

    def GetUserById(self, request, context):
        if request.uuid in users:
            return users[request.uuid]
        context.set_code(grpc.StatusCode.NOT_FOUND)
        context.set_details("User not found")
        return pb.User()

class RoomService(pb_grpc.RoomServiceServicer):
    def CreateRoom(self, request, context):
        room_id = str(uuid.uuid4())
        new_room = pb.Room(
            id=pb.Id(uuid=room_id),
            name=request.name,
            participantIds=request.participantIds,
            type=request.type,
            creatorId=request.creatorId,
            password=request.password,
        )
        rooms[room_id] = new_room
        room_messages[room_id] = []
        return pb.Ack(success=True, message=room_id)

    def JoinRoom(self, request, context):
        room_id = request.roomId.uuid
        if room_id in rooms:
            return pb.Ack(success=True, message=f"Joined room {room_id}")
        return pb.Ack(success=False, message="Room not found")

    def LeaveRoom(self, request, context):
        return pb.Ack(success=True, message="Left room")

    def GetRoomParticipants(self, request, context):
        room_id = request.uuid
        if room_id in rooms:
            participant_ids = rooms[room_id].participantIds
            participants = [users[pid.uuid] for pid in participant_ids if pid.uuid in users]
            return pb.RoomParticipants(roomId=pb.Id(uuid=room_id), participants=participants)
        return pb.RoomParticipants()

class ChatService(pb_grpc.ChatServiceServicer):
    def SendTextMessage(self, request, context):
        room_id = request.recipientId.uuid
        if room_id not in room_messages:
            room_messages[room_id] = []
        now = Timestamp()
        now.GetCurrentTime()
        request.timestamp.CopyFrom(now)
        room_messages[room_id].append(request)
        return pb.Ack(success=True, message="Message sent")

    def ReceiveTextMessages(self, request, context):
        room_id = request.uuid
        for message in room_messages.get(room_id, []):
            yield message
            time.sleep(0.1)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_UserServiceServicer_to_server(UserService(), server)
    pb_grpc.add_RoomServiceServicer_to_server(RoomService(), server)
    pb_grpc.add_ChatServiceServicer_to_server(ChatService(), server)
    server.add_insecure_port('[::]:8008')
    print("\u2728 Kasugai gRPC server started on port 8008")
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
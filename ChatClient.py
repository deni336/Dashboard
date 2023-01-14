import grpc
import protos.kasugai_pb2
import protos.kasugai_pb2_grpc

class ChatClient():
    def __init__(self) -> None:
        with grpc.insecure_channel('localhost:6969') as channel:
            self.connection(channel)

    def connection(self, channel):
        self.conn = protos.kasugai_pb2_grpc.BroadcastStub(channel)

    def sendMessage(self, message):
        n = protos.kasugai_pb2.MessageResponse()
        n.message = message
        n.timestamp = ""
        response = self.conn.ChatService(n)
        print(response)


    def recMessage(self):
        for msg in self.conn.ChatService(protos.kasugai_pb2.MessageResponse()):
            print(msg)
        

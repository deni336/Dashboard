import grpc
import protos.kasugaipy_pb2
import protos.kasugaipy_pb2_grpc

class ChatClient():
    
    def connection(self):
        self.channel = grpc.insecure_channel(target="localhost:6969")
        self.conn = protos.kasugaipy_pb2_grpc.BroadcastStub(self.channel)
        

    def sendMessage(self, message):
        n = protos.kasugaipy_pb2.MessageResponse()
        n.message = message
        self.conn.ChatService(n)


    def recMessage(self):
        for msg in self.conn.ChatService(protos.kasugaipy_pb2.MessageResponse()):
            print(msg)
        

class PBUser():
    
    user = protos.kasugaipy_pb2.User()
    user.name = "Deni"

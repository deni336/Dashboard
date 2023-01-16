import grpc
import protos.kasugai_pb2 as kasugaipy_pb2
import protos.kasugai_pb2_grpc as kasugaipy_pb2_grpc
             
class ChatClient():
    
    def widgets(self):
        self.addr = "localhost:6969"
        self.channel = grpc.insecure_channel(self.addr)
        self.stub = kasugaipy_pb2_grpc.BroadcastStub
        self.msg = kasugaipy_pb2.MessageResponse(message=self.addr)

    widgets(self=widgets)

    def sendMessage(self):
        pass

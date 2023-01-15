import grpc
import protos.kasugai_pb2
import protos.kasugai_pb2_grpc

class ChatClient():
    
    channel = grpc.insecure_channel('localhost:6969')
    conn = protos.kasugai_pb2_grpc.BroadcastStub(channel)
    iterator = 0

    def sendMessage(self, message):
        
        n = protos.kasugai_pb2.MessageResponse()
        n.message = message
        n.timestamp = ""
        response = self.conn.ChatService(n, self.iterator)
        self.iterator += 1
        print(response)


    def recMessage(self):
        msg = self.conn.ChatService(protos.kasugai_pb2.MessageResponse())
        print(msg)
        

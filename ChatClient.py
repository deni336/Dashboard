import grpc
import protos.kasugaipy_pb2 as kasugaipy_pb2
import protos.kasugaipy_pb2_grpc as kasugaipy_pb2_grpc
             
class ChatClient():
    
    def __init__(self):
        self.addr = "localhost:6969"
        self.channel = grpc.insecure_channel(self.addr)
        self.stub = kasugaipy_pb2_grpc.BroadcastStub
        self.msg = kasugaipy_pb2.MessageResponse(message=self.addr)
        
    def make_message(self, message):
        return kasugaipy_pb2.MessageResponse(
            message=message
        )
        
    def send_messages(self):
        #self.msg = "Hello world"
        messages = [self.make_message(self.msg),]       
        for msg in messages:
            print("Sending message to server %s" % msg.message)
            self.msg = msg.message
            yield msg
            
    async def servConn(self):
        async with self.channel as channel:
            self.stub = kasugaipy_pb2_grpc.BroadcastStub(channel)
            messages = await self.stub.ChatService(self.send_messages())
            for msg in messages:
                print("R[{}] {}".format(msg.message, msg.timestamp))
                self.msg = msg

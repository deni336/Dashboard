import grpc
import threading
from datetime import datetime
import protos.kasugai_pb2
import protos.kasugai_pb2_grpc
             
class ChatCl():
    def __init__(self):
        self.addr = "localhost:6969"
        self.channel = grpc.insecure_channel(self.addr)
        self.stub = protos.kasugai_pb2_grpc.BroadcastStub
        self.msg = protos.kasugai_pb2.MessageResponse(message=self.addr)
        threading.Thread(target=self.listener).start()
    
    def listener(self):
        self.stub = protos.kasugai_pb2_grpc.BroadcastStub(self.channel)
        while True:
            messages = self.stub.ChatStream(self.msg)
            for msg in messages:
                self.msg = msg.message
    
    
    
    # def make_message(self, message):
    #     self.resp = kasugaipy_pb2.MessageResponse(
    #         message=message,
    #         timestamp=datetime.now().strftime("%H:%M:%S"),
    #     )
    
    # def send_messages(self):
    #     messages = [self.resp]        
    #     for msg in messages:
    #         print("Sending message to server %s" % msg.message)
    #         yield msg
            
    # def servConn(self):
    #     #with self.channel as channel:
    #         self.stub = kasugaipy_pb2_grpc.BroadcastStub(self.channel)
    #         messages = self.stub.ChatService(self.msg)
    #         for msg in messages:
    #             print("Response from server [{}] {}".format(msg.message, msg.timestamp))
    #             self.msg = msg
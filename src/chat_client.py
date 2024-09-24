import grpc
import threading
from datetime import datetime
import client.protos.kasugai_pb2 as kasugaipy_pb2
import client.protos.kasugai_pb2_grpc as kasugaipy_pb2_grpc
             
class ChatCl():
    def __init__(self):
        self.addr = "localhost:6969"
        self.channel = grpc.insecure_channel(self.addr)
        self.stub = kasugaipy_pb2_grpc.BroadcastStub
        self.resp = kasugaipy_pb2.MessageResponse(message="test")
        self.msg = kasugaipy_pb2.MessageResponse(message=self.addr)
        threading.Thread(target=self.servConn).start()
    
    def make_message(self, message):
        self.resp = kasugaipy_pb2.MessageResponse(
            message=message,
            timestamp=datetime.now().strftime("%H:%M:%S"),
        )
    
    def send_messages(self):
        messages = [self.resp]        
        for msg in messages:
            print("Sending message to server %s" % msg.message)
            yield msg
            
    def servConn(self):
        #with self.channel as channel:
            self.stub = kasugaipy_pb2_grpc.BroadcastStub(self.channel)
            messages = self.stub.ChatService(self.msg)
            
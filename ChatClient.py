import grpc
import threading
from datetime import datetime
import protos.kasugai_pb2
import protos.kasugai_pb2_grpc

class ChatCl():
    def __init__(self):
        self.addr = "localhost:6969"
        try:
            self.channel = grpc.insecure_channel(self.addr)
            self.stub = protos.kasugai_pb2_grpc.BroadcastStub
        except grpc.RpcError as e:
            print("Failed to connect to server", e)
        self.msg = protos.kasugai_pb2.MessageResponse(message=self.addr)
        threading.Thread(target=self.listener).start()
    
    def listener(self):
        self.stub = protos.kasugai_pb2_grpc.BroadcastStub(self.channel)
        sub = self.channel.subscribe(callback=False)
        while :
            messages = self.stub.ChatStream(self.msg)
            for msg in messages:
                self.msg = msg.message
    
    def sendMsg(self, inputMessage):
        try:
            self.msg = protos.kasugai_pb2.MessageResponse(message = inputMessage)
            self.stub.SendMessage(self.msg)
        except grpc.RpcError as e:
            print("Failed to send message", e)


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
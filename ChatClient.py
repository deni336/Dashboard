import socket
import threading
import grpc
import protos.kasugaipy_pb2 as kasugaipy_pb2
import protos.kasugaipy_pb2_grpc as kasugaipy_pb2_grpc
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
             
class ChatClient():
    
    def __init__(self):
        self.addr = "localhost:6969"
        self.channel = grpc.insecure_channel(self.addr)
        self.stub = kasugaipy_pb2_grpc.BroadcastStub
        self.msg = kasugaipy_pb2.MessageResponse(message=self.addr)
    
    

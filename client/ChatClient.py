import asyncio
from grpc import *
import threading
from datetime import datetime
import client.protos.kasugai_pb2 as chat
import client.protos.kasugai_pb2_grpc as rpc
from client.protos.kasugai_pb2 import MessageResponse
from client.protos.kasugai_pb2_grpc import BroadcastStub

class ChatCl():
    def __init__(self):
        pass
    #     self.addr = "localhost:6969"
    #     try:
    #         self.channel = Channel()
    #         self.stub = BroadcastStub
    #     except RpcError as e:
    #         print("Failed to connect to server", e)
        
    # async def chatSub(self, msg):
    #     messages = [MessageResponse(message = msg, timestamp = datetime.now()), MessageResponse(message = msg, timestamp = datetime.now())]
    #     print(await self.stub.ChatService)
    
    
    
    # def listener(self):
    #     self.stub = protos.kasugai_pb2_grpc.BroadcastStub(self.channel)
    #     sub = self.channel.subscribe(callback=False)
    #     while True:
    #         messages = self.stub.ChatStream(self.msg)
    #         for msg in messages:
    #             self.msg = msg.message
    
    # def sendMsg(self, inputMessage):
    #     try:
    #         self.msg = protos.kasugai_pb2.MessageResponse(message = inputMessage)
    #         self.stub.SendMessage(self.msg)
    #     except grpc.RpcError as e:
    #         print("Failed to send message", e)


    
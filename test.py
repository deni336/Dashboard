from grpc import *
import protos.kasugai_pb2 as chat
import protos.kasugai_pb2_grpc as rpc

taskQue = []

stub = rpc.BroadcastStub

async def chatSub():
    async with Channel("localhost", "6969") as channel:
        pass

    async with stub.ChatService.open() as stream:
            await stream.ChatService()

def que(self, inp):
    taskQue.append(inp)

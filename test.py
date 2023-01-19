from grpc import *


async def chatSub():
    async with Channel("localhost", "6969") as channel:
        pass
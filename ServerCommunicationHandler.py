import asyncio
from distutils.command.config import config
import logging

import grpc
import kasugai_pb2
import kasugai_pb2_grpc

from ConfigHandler import *

configDict = getConfig()

# For more channel options, please see https://grpc.io/grpc/core/group__grpc__arg__keys.html
CHANNEL_OPTIONS = [('grpc.lb_policy_name', 'pick_first'),
                   ('grpc.enable_retries', 0),
                   ('grpc.keepalive_timeout_ms', 10000)]


async def run(method, message) -> None:
    
    async with grpc.aio.insecure_channel(target='localhost:50051',
                                         options=CHANNEL_OPTIONS) as channel:
        stub = kasugai_pb2_grpc.GreeterStub(channel)
        response = await stub.method(kasugai_pb2.method(message, name=configDict['user']),
                                       timeout=10)
    return response
    


if __name__ == '__main__':
    logging.basicConfig()
    asyncio.run(run())
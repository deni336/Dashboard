from concurrent import futures

import grpc
import time

import protos.kasugai_pb2 as chat
import protos.kasugai_pb2_grpc as rpc

class ChatServer(rpc.BroadcastServicer):
    def __init__(self) -> None:
        self.chats = []
        

    def chatStream(self, request_iterator, context):
        lastIndex = 0
        while True:
            while len(self.chats) > lastIndex:
                n = self.chats[lastIndex]
                lastIndex += 1
                yield n
    def sendNote(self, request: chat.MessageResponse, context):
        print("[{}] {}".format(request.name, request.message))
        self.chats.append(request)
        return chat.Empty()

if __name__ == '__main__':
    port = 6969
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    rpc.add_BroadcastServicer_to_server(ChatServer(), server)
    print('Starting server. Listening...')
    server.add_insecure_port('[::]:' + str(port))
    server.start()
    while True:
        time.sleep(64*64*100)
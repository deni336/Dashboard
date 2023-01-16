import grpc
import threading
import sys
import protos.kasugai_pb2 as kasugaipy_pb2
import protos.kasugai_pb2_grpc as kasugaipy_pb2_grpc
             
class ChatClient():
    def __init__(self) -> None:
        self.runThread()
    
    addr = "localhost:6969"
    channel = grpc.insecure_channel(addr)
    stub = kasugaipy_pb2_grpc.BroadcastStub
    msg = kasugaipy_pb2.MessageResponse()
    

    def recvMessages(self):
        self.stub = kasugaipy_pb2_grpc.BroadcastStub(self.channel)
        messages = self.stub.ChatService(self.msg)
        for msg in messages:
            print("R[{}] {}".format(msg.message, msg.timestamp))
            self.msg = msg
        
    def sendMessage(self, inputMessage):
        messages = inputMessage
        for msg in messages:
            print("Sending message to server %s" % msg.message)
            self.broadcast = msg.message
            yield msg

    def runThread(self):
        try:
            messageThread = threading.Thread(target=self.recvMessages)
            messageThread.start()
        except (KeyboardInterrupt, SystemExit):
            sys.exit()
    
# ChatClient.runThread(ChatClient)                   
    # Example to get server connection working
    # def servConn(self):
    #         self.connection.stub = kasugaipy_pb2_grpc.BroadcastStub(self.connection.channel)
    #         messages = self.connection.stub.ChatService(self.recvMessages())
    #         for msg in messages:
    #             print("R[{}] {}".format(msg.message, msg.timestamp))

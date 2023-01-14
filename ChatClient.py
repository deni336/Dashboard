import os
import socket
import subprocess
import protos.kasugaipy_pb2
import protos.kasugaipy_pb2_grpc
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

PORT = 6969

def connection(user, ip = "localhost"):

    server.connect((ip, PORT))
    ChatClient.sendMessage(user)
    return

class ChatClient():
    
    def sendMessage(message):
        server.send(bytearray(message.replace('\x00', '') + '\n', 'utf-8'))
        return

    def recMessage(self):
        while server:
            try:
                data = server.recv(1024)
                output = data.decode("utf_8")
                if data != None:
                    return output
            except:
                return

    def ServerConnection(user, ip = "localhost"):
        pass

class User():
    user = protos.kasugaipy_pb2.User()
    send = protos.kasugaipy_pb2.MessageResponse()
    send.Message = "Hello from bob"
    send.Timestamp = "1800"
    user.Name = 'Bob'
    user.Message = send
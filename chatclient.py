import socket
import os
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
   
PORT = 6969
def connection(user, ip = "192.168.45.10"):
    server.connect((ip, PORT))
    socketHandling.sendMessage(user)
    return

class socketHandling():
    def sendMessage(message):
        server.send(bytearray(message.replace('\x00', '') + '\n', 'utf-8'))
        return

    def recMessage():
        while server:
            try:
                data = server.recv(1024)
                output = data.decode("utf_8")
                if data != None:
                    return output
            except:
                return


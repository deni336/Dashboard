from encodings import utf_8
import socket

global server
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
HOST = "127.0.0.1"
PORT = 6969
def connection(user):
    server.connect((HOST, PORT))
    server.send(user.encode('utf-8'))
    return

class socketHandling():
    def sendMessage(message):
        server.send(message.encode('utf-8'))
        return


    def recMessage():
        while server:
            data = server.recv(1024)
            output = data.decode("utf_8")
            if data != None:
                return output
            


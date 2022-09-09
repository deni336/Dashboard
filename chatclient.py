from encodings import utf_8
import socket


global server
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
HOST = "127.0.0.1"
PORT = 6969
def connection(user):
    server.connect((HOST, PORT))
    server.send(bytearray(user + '\n', 'utf-8'))
    return

class socketHandling():
    def sendMessage(message):
        server.send(bytearray(message + '\n', 'utf-8'))
        return

    def recMessage():
        while server:
            data = server.recv(1024)
            output = data.decode("utf_8")
            if data != None:
                return output
    
    def close():
        server.close()
            


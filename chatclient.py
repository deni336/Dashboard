import socket

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
# server.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
HOST = "192.168.45.10"
#HOST = "127.0.0.1"
PORT = 6969
def connection(user):
    server.connect((HOST, PORT))
    socketHandling.sendMessage(user)
    
    return

class socketHandling():
    def sendMessage(message):
        a = server.send(bytearray(message.replace('\x00', '') + '\n', 'utf-8'))
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


import socket

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
HOST = "192.168.45.10"
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
            try:
                data = server.recv(1024)
                output = data.decode("utf_8")
                if data != None:
                    return output
            except:
                return
    
    def close(message):
        server.send(bytearray(message + '\n', 'utf-8'))
        server.close()
        return


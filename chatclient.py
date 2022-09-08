import socket

HOST = "192.168.1.179"  # The server's hostname or IP address
PORT = 6969  # The port used by the server

def sendMessage(message):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))
        s.sendall(b'{message}')
        data = s.recv(1024)
    return data

def recMessage(message):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))
        s.listen()
        data = s.recv(1024)

    print(f"Received {data!r}")
import socket

HOST = "127.0.0.1"  # The server's hostname or IP address
PORT = 6969  # The port used by the server

# def sendMessage(message):
#     with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
#         s.connect((HOST, PORT))
#         s.sendall(b'{message}')
#         data = s.recv(1024)
#     return data


with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind((HOST, PORT))
    while True:
        s.listen()
        data = s.recv(1024)

    print(f"Received {data!r}")
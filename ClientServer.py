import socket
import tqdm
import os
import ConfigHandler
# device's IP address
SERVER_HOST = "192.168.45.10"
SERVER_PORT = 6968
# receive 4096 bytes each time
BUFFER_SIZE = 4096
SEPARATOR = "<SEPARATOR>"

class ClientServer():

    def __init__(self):
        self.s = socket.socket()
        self.s.bind((SERVER_HOST, SERVER_PORT))
        self.s.listen(5)
        print(f"[*] Listening as {SERVER_HOST}:{SERVER_PORT}")
        self.client_socket, address = self.s.accept()
        print(f"[+] {address} is connected.")
        self.received = self.client_socket.recv(BUFFER_SIZE).decode()
        filename, filesize = self.received.split(SEPARATOR)
        filename = os.path.basename(filename)
        filesize = int(filesize)
        ClientServer.receive(self)

    def receive(self):

        configDict = ConfigHandler.getConfig()

        filename, filesize = self.received.split(SEPARATOR)

        filename = os.path.basename(filename)

        filesize = int(filesize)

        saveDir = configDict.get('workDir') + "/" + filename

        progress = tqdm.tqdm(range(filesize), f"Receiving {filename}", unit="B", unit_scale=True, unit_divisor=1024)

        with open(saveDir, "wb") as f:
            while True:
                # read 1024 bytes from the socket (receive)
                bytes_read = self.client_socket.recv(BUFFER_SIZE)
                if not bytes_read:    
                    # nothing is received
                    # file transmitting is done
                    break
                # write to the file the bytes we just received
                f.write(bytes_read)
                # update the progress bar
                progress.update(len(bytes_read))

        # close the client socket
        self.client_socket.close()

    def sendHook():
        ip = socket.socket.getsockname()
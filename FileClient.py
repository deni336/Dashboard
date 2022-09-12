import socket
from tkinter import SEPARATOR
import tqdm
import os
import ConfigHandler

SEPARATOR = "<SEPARATOR>"

BUFFER_SIZE = 4096

#host = '192.168.45.10'

port = 6968

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

class FileSender():

    def fileConnection(self, ip):
        server.connect(ip, port)

    def sendingFile(filename, size):
        server.send(f"{filename}{SEPARATOR}{size}".encode())
        progress = tqdm.tqdm(range(size), f"Sending {filename}", unit="B", unit_scale=True, unit_divisor=1024)
        with open(filename, "rb") as f:
            while True:
                # read the bytes from the file
                bytes_read = f.read(BUFFER_SIZE)
                if not bytes_read:
                    # file transmitting is done
                    break
                # we use sendall to assure transimission in 
                # busy networks
                server.sendall(bytes_read)
                # update the progress bar
                progress.update(len(bytes_read))
        # close the socket
        server.close()
    
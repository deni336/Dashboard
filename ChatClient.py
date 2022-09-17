import socket
import os
import subprocess
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

PORT = 6969

def connection(user, ip = "192.168.45.69"):
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

    def ServerConnection(user, ip = "192.168.45.69"):
        try:
            serv = subprocess.Popen([r"chat.exe"])
            b = serv.pid
            
            if user == '':
                user = os.getlogin()
                connection(user, ip)
                return [b, '']
            else:
                connection(user, ip)
                return [b, '']
        except:
                return [b, "No Server Connected"]

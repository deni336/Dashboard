import os
import socket
import subprocess
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

PORT = 6969

def connection(user, ip = "localhost"):

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

    def ServerConnection(user, ip = "localhost"):
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

    def sendStage(self, stagedList):
        server.send(bytearray(stagedList.replace('\x00', '') + '\n', 'utf-8'))

    def servCall():
        pass


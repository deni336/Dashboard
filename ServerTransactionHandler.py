import os
import socket
import subprocess
import time

import ChatClient
from ConfigHandler import *

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

class ServerTransactionHandler():
    configDict = getConfig()
    IP = configDict["clientIp"]
    PORT = "6970"

    def retrieveLists(self, user):
        num = 0
        try:
            server.connect((self.IP, self.PORT))
            server.send(bytearray(user.replace('\x00', '') + '\n', 'utf-8'))
            data = server.recv(1024)
            output = data.decode("utf_8")
            server.close()
            return output
        except:            
            while num > 5:
                self.retrieveLists(self.configDict['user'])
                time.sleep(10)
                num += 1
                print("Pulse Failed - Retry in 10 sec")

    def checkIp(self):
        ip = socket.socket.getsockname(ChatClient.server)
        if self.configDict['clientIp'] == ip[0]:
            pass
        else:
            update('clientIp', ip[0])

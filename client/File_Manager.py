# from ChatClient import ChatCl
import client.config_handler as config_handler

class FileManager():
    configDict = config_handler.getConfig()
    
    def whats_avail(self):
        self.configDict = config_handler.getConfig()
        self.listOfAvailFiles = self.configDict.get('download')
        return self.listOfAvailFiles

    def download():
        pass

    def delete(self, filename):
        self.listOfAvailFiles.remove(filename)
        config_handler.update('download', self.listOfAvailFiles)


    def stage(self, ip, size, path):
        self.listOfAvailFiles.append([ip, size, path])
        config_handler.update('download', self.listOfAvailFiles)
        # ChatClient.sendStage(ChatClient[ip, size, path])
    
    


# from ChatClient import ChatCl
import config_manager as ConfigHandler

class FileManager():
    def __init__(self) -> None:
        self.config = ConfigHandler()
    
    def whatsAvail(self):
        self.config = ConfigHandler()
        self.listOfAvailFiles = self.config.get('FileTransfer', 'avail')
        return self.listOfAvailFiles

    def download():
        pass

    def delete(self, filename):
        self.listOfAvailFiles.remove(filename)
        ConfigHandler.update('download', self.listOfAvailFiles)


    def stage(self, ip, size, path):
        self.listOfAvailFiles.append([ip, size, path])
        ConfigHandler.update('download', self.listOfAvailFiles)
        # ChatClient.sendStage(ChatClient[ip, size, path])
    

# This needs to be an API

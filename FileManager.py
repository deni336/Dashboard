import ConfigHandler

class FileManager():
    configDict = ConfigHandler.getConfig()
    
    def whatsAvail(self):
        self.configDict = ConfigHandler.getConfig()
        self.listOfAvailFiles = self.configDict.get('download')
        return self.listOfAvailFiles

    def download():
        pass

    def delete(self, filename):
        self.listOfAvailFiles.remove(filename)
        ConfigHandler.update('download', self.listOfAvailFiles)


    def stage(self, path):
        self.listOfAvailFiles.append(path)
        ConfigHandler.update('download', self.listOfAvailFiles)
    
    


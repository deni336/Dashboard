import os, sys
import ConfigHandler

class FileManager():
    
    def whatsAvail(self):
        configDict = ConfigHandler.getConfig()
        listOfAvailFiles = configDict.get('download')
        return listOfAvailFiles

    def download():
        pass

    def stage(filename, path):
        ConfigHandler.update(filename, path)


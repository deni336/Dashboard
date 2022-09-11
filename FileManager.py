import os, sys
import confighandler

class FileManager():
    
    def whatsAvail(self):
        configDict = confighandler.getConfig()
        listOfAvailFiles = configDict.get('download')
        return listOfAvailFiles

    def download():
        pass

    def stage(filename, path):
        confighandler.update(filename, path)


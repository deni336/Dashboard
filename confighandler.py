import json
import re

def setUser(name):
    userDict = {"user" : name}
    username = json.dumps(userDict, indent=4)
    f = open("config.json", "w")
    f.write(username)
    f.close()

def getConfig():
    try:
        with open("config.json", "r") as configFile:
            fileContent = configFile.read()
            configDict = json.loads(fileContent)
            return configDict
    except:
        with open("config.json", "w") as configFile:
            return None

def loadUser():
    configDict = getConfig()
    if configDict == None:
        return None
    else:
        for key in configDict.keys():
            if key == "user":
                user = configDict.get(key)
        return user









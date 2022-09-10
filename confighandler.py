import json

def setUser(name):
    configDict = getConfig()
    configDict.update({"user": name})
    saveConfig(configDict)

def getConfig():
    try:
        with open("config.json", "r") as configFile:
            fileContent = configFile.read()
            configDict = json.loads(fileContent)
            return configDict
    except:
        with open("config.json", "w") as configFile:
            return None
    
def saveConfig(configDict):
    with open("config.json", "w") as f:
        dumped = json.dumps(configDict, indent=4)
        f.write(dumped)
        f.close()

def loadUser():
    configDict = getConfig()
    if configDict.get('user') == None:
        return None
    else:
        user = configDict.get('user')
        return user

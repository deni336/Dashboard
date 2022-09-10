import json

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
    
def saveConfig(configDict):
    with open("config.json", "w") as f:
        dumped = json.dumps(configDict, indent=4)
        f.write(dumped)
        f.close()

def loadUser():
    configDict = getConfig()
    if configDict == None:
        return None
    else:
        for key in configDict.keys():
            if key == "user":
                user = configDict.get(key)
        return user

def setBackground(bg):
    bgSave = {"background" : bg}
    bgWrite = json.dumps(bgSave, indent=4)
    f = open("config.json", "w")
    f.write(bgWrite)
    f.close()

def setForeground(fg):
    fgSave = {"background" : fg}
    fgWrite = json.dumps(fgSave, indent=4)
    f = open("config.json", "w")
    f.write(fgWrite)
    f.close()









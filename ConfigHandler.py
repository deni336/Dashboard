import json
import os

user = os.getlogin()

def update(key, value):
    configDict = getConfig()
    configDict.update({key: value})
    saveConfig(configDict)

def getConfig():
    try:
        with open("C:/users/" + user + "/dashconfig.json", "r") as configFile:
                fileContent = configFile.read()
                configDict = json.loads(fileContent)
                return configDict
                
    except:
        with open("C:/users/" + user + "/dashconfig.json", "w") as configFile:
            configF = {
                "user": "",
                "buttonBackground": "#000000",
                "buttonForeground": "#ff0000",
                "buttonFont": "American Typewriter",
                "buttonFontsize": "12",
                "buttonFontadd": "bold",
                "labelFont": "('helvetica', 16, 'bold italic')",
                "labelForeground": "#ff0000",
                "frameBackground": "#000000",
                "bgImage": "bg.jpg",
                "windowMode": "True",
                "download": [],
                "workDir": "",
                "keyBinds": []
            }
            saveConfig(configF)
            with open("C:/users/" + user + "/dashconfig.json", "r") as configFile:
                fileContent = configFile.read()
                configDict = json.loads(fileContent)
                return configDict
        
    
def saveConfig(configD):
    with open("C:/users/" + user + "/dashconfig.json", "w") as f:
        dumped = json.dumps(configD, indent=4)
        f.write(dumped)
        f.close()

def loadUser():
    configDict = getConfig()
    if configDict.get('user') == None:
        return None
    else:
        user = configDict.get('user')
        return user

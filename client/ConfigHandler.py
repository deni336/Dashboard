import json
import os
from pathlib import Path
from client.config import Config

user = os.getlogin()
configPath = Path().home().joinpath("dashconfig.json")
#config_file = cfg.Config
protoDict = {}
   
# # This needs to be self.config_file   
# def getConfig() -> cfg.Config:
#     return load_config()
    
def generate_config():
    return {
            "user": "",
            "buttonBackground": "#000000",
            "buttonForeground": "#ff0000",
            "buttonFont": "American Typewriter",
            "buttonFontsize": "12",
            "buttonFontadd": "bold",
            "labelFont": "('helvetica', 16, 'bold italic')",
            "labelForeground": "#ff0000",
            "frameBackground": "#000000",
            "bgImage": "Miku.jpg",
            "windowMode": "True",
            "download": [],
            "workDir": "",
            "keyBinds": [],
            "clientIp": ""
        }
     
     
# def load_config():
#     try:
#         with open(configPath, "r") as configFile:
#                 fileContent = configFile.read()
#                 configDict = cfg.Config(**json.loads(fileContent))
#                 return configDict            
#     except:
#         return cfg.Config(**generate_config())

def getConfig():
    try:
        with open(configPath, "r") as configFile:
                fileContent = configFile.read()
                configDict = json.loads(fileContent)
                return configDict            
    except:
        return generate_config()
        
    
def saveConfig(configD):
    with open(configPath, "w") as f:
        dumped = json.dumps(configD, indent=4)
        f.write(dumped)
        
def update(key, value):
    configDict = getConfig()
    configDict.update({key: value})
    saveConfig(configDict)

def loadUser():
    configDict = getConfig()
    if configDict.get('user') == None:
        return None
    else:
        user = configDict.get('user')
        return user

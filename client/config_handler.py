import json
import os
from pathlib import Path
from client.config import Config

user = os.getlogin()
config_path = Path().home().joinpath("dashconfig.json")
#config_file = cfg.Config
proto_dict = {}
   
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
            "bgImage": "bg.jpg",
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

def get_config():
    try:
        with open(config_path, "r") as config_file:
                file_content = config_file.read()
                config_dict = json.loads(file_content)
                return config_dict            
    except:
        return generate_config()
        
    
def save_config(configD):
    with open(config_path, "w") as f:
        dumped = json.dumps(configD, indent=4)
        f.write(dumped)
        
def update(key, value):
    config_dict = get_config()
    config_dict.update({key: value})
    save_config(config_dict)

def load_user():
    config_dict = get_config()
    if config_dict.get('user') == None:
        return None
    else:
        user = config_dict.get('user')
        return user

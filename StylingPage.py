from tkinter import ttk
from ConfigHandler import *

configDict = getConfig()

frameSytles = {"background:": "self.configDict.get('frameBackground')",
               "foreground:": "foreground=self.configDict.get('labelForeground')",
               "font=":"self.configDict.get('labelFont')"}

def styler():
    style = ttk.Style()
    style.theme_use('default')
    style.configure('W.TButton', foreground=configDict.get('buttonForeground'), background=configDict.get('buttonBackground'), fill="both", borderwidth="5", relief="ridge", font=
                    (configDict.get('buttonFont'), configDict.get("buttonFontsize"), configDict.get("buttonFontadd")))
    return style

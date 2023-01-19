from tkinter import ttk
from client.ConfigHandler import *

configDict = getConfig()

def styler():
    style = ttk.Style()
    style.theme_use('default')
    style.configure('W.TButton', foreground=configDict.get('buttonForeground'), background=configDict.get('buttonBackground'), fill="both", borderwidth="5", relief="ridge", font=
                    (configDict.get('buttonFont'), configDict.get("buttonFontsize"), configDict.get("buttonFontadd")))
    return style

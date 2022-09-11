from tkinter import ttk
from confighandler import *

configDict = getConfig()

frameSytles = {"bg": "configDict.get('frameBackground')",
               "fg": "configDict.get('labelForeground')"}

def styler():
    style = ttk.Style()
    style.theme_use('default')
    style.configure('W.TButton', foreground=configDict.get('buttonForeground'), background=configDict.get('buttonBackground'), fill="both", borderwidth="5", relief="ridge", font=
                    (configDict.get('buttonFont'), configDict.get("buttonFontsize"), configDict.get("buttonFontadd")))
    return style

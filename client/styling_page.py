from tkinter import ttk
from client.config_handler import *

config_dict = get_config()

def styler():
    style = ttk.Style()
    style.theme_use('default')
    style.configure('W.TButton', foreground=config_dict.get('buttonForeground'), background=config_dict.get('buttonBackground'), fill="both", borderwidth="5", relief="ridge", font=
                    (config_dict.get('buttonFont'), config_dict.get("buttonFontsize"), config_dict.get("buttonFontadd")))
    return style

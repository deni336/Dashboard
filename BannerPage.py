from tkinter import *
from tkinter import ttk
from ConfigHandler import *
import StylingPage
import ChatPage, SettingsPage

class BannerF(Frame):
    configDict = getConfig()
    settingsBool = False
    chatBool = False
    def __init__(self, parent, controller):
        self.style = StylingPage.styler()
        Frame.__init__(self, parent)
        self.parent = parent
        self.configure(background=self.configDict.get('frameBackground'))
        self.widgets()

    def widgets(self):
        self.pack(fill="x", side="top")

        self.appLabel = ttk.Label(self, text="Kasugai", background=self.configDict.get("frameBackground"), foreground=self.configDict.get("labelForeground"), font=("American typewriter", 25))
        self.appLabel.pack(side="left")

        self.exitBtn = ttk.Button(self, text="Exit", style="W.TButton", cursor="hand2",
                        command= lambda: self.shutdown())
        self.exitBtn.pack(side="right")

        self.minimizeBtn = ttk.Button(self, text="Minimize", style="W.TButton", cursor="hand2", command= lambda: self.state("icon"))
        self.minimizeBtn.pack(side="right")

        self.downsizeBtn = ttk.Button(self, text="Downsize", style="W.TButton", cursor="hand2", command= lambda: self.wm_attributes("-fullscreen", False))
        self.downsizeBtn.pack(side="right")

        self.maximizeBtn = ttk.Button(self, text="Fullscreen", style="W.TButton", cursor="hand2", command= lambda: self.wm_attributes("-fullscreen", True))
        self.maximizeBtn.pack(side="right")

        self.settingsBtn = ttk.Button(self, text="Settings", style="W.TButton", cursor="hand2",
                                command= lambda: SettingsPage.SettingsW.toggleSettings(SettingsPage.SettingsW))
        self.settingsBtn.pack(side="right")

        self.chatBtn = ttk.Button(self, text="Chatticus", style="W.TButton", cursor="hand2",
                            command= lambda: ChatPage.ChatF.toggleBool(ChatPage.ChatF))
        self.chatBtn.pack(side="right", pady=5)

            
            


        



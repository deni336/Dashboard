from tkinter import *
from tkinter import ttk
from confighandler import *
import StylingPage

class BannerF(Frame):
    def __init__(self, parent, e):
        self.event = e
        self.configDict = getConfig()
        self.settingsBool = False
        self.chatBool = False
        self.style = StylingPage.styler()
        Frame.__init__(self, parent)
        self.parent = parent
        self.configure(background=self.configDict.get('frameBackground'))
        self.widgets()

    def widgets(self):
        self.appLabel = ttk.Label(self, text="Kasugai", background=self.configDict.get('frameBackground'), foreground=self.configDict.get("labelForeground"), font=("American typewriter", 25))
        self.appLabel.pack(side="left")

        self.exitBtn = ttk.Button(self, text="Exit", style="W.TButton", cursor="hand2",
                        command= lambda: self.event.OnShutDown())
        self.exitBtn.pack(side="right")

        self.minimizeBtn = ttk.Button(self, text="Minimize", style="W.TButton", cursor="hand2", command= lambda: self.event.Minimize())
        self.minimizeBtn.pack(side="right")

        self.downsizeBtn = ttk.Button(self, text="Downsize", style="W.TButton", cursor="hand2", command= lambda: self.event.DownSize())
        self.downsizeBtn.pack(side="right")

        self.maximizeBtn = ttk.Button(self, text="Fullscreen", style="W.TButton", cursor="hand2", command= lambda: self.event.FullScreen())
        self.maximizeBtn.pack(side="right")

        self.settingsBtn = ttk.Button(self, text="Settings", style="W.TButton", cursor="hand2", 
                                      command= lambda: self.event.OnLockBroken())
        self.settingsBtn.pack(side="right")

        self.chatBtn = ttk.Button(
            self, 
            text="Chatticus", 
            style="W.TButton", 
            cursor="hand2",
            command= lambda: self.event.ToggleOpen()
        )
        
        self.chatBtn.pack(side="right", pady=5)
        
        self.pack(fill="x", side="top")
        
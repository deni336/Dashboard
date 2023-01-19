from tkinter import *
from tkinter import ttk
from client.ConfigHandler import *
import client.StylingPage as StylingPage

class BannerF(Frame):
    def __init__(self, parent, e):
        self.event = e
        self.configDict = getConfig()
        self.settingsBool = False
        self.chatBool = False
        self.servTransBool = False
        Frame.__init__(self, parent)
        self.parent = parent
        self.configure(background=self.configDict['frameBackground'])
        self.widgets()

    def widgets(self):
        self.appLabel = ttk.Label(
            self,
            text="Kasugai", 
            background=self.configDict['frameBackground'], 
            foreground=self.configDict["labelForeground"], 
            font=("American typewriter", 25)
        ).pack(side="left")

        self.exitBtn = ttk.Button(
            self, 
            text="Exit", 
            style="W.TButton", 
            cursor="hand2",
            command= lambda: self.event.OnShutDown()
        ).pack(side="right")

        self.minimizeBtn = ttk.Button(
            self, 
            text="Minimize", 
            style="W.TButton", 
            cursor="hand2",
            command= lambda: self.event.Minimize()
        ).pack(side="right")

        self.downsizeBtn = ttk.Button(
            self, 
            text="Downsize", 
            style="W.TButton", 
            cursor="hand2",
            command= lambda: self.event.DownSize()
        ).pack(side="right")

        self.maximizeBtn = ttk.Button(
            self, 
            text="Fullscreen", 
            style="W.TButton", 
            cursor="hand2",
            command= lambda: self.event.FullScreen()
        ).pack(side="right")

        self.settingsBtn = ttk.Button(
            self, 
            text="Settings", 
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: self.event.OnLockBroken()
        ).pack(side="right")

        self.chatBtn = ttk.Button(
            self, 
            text="Chatticus", 
            style="W.TButton", 
            cursor="hand2",
            command= lambda: self.event.ToggleOpen()
        ).pack(side="right", pady=5)
        
        self.servTransBtn = ttk.Button(
            self, 
            text="Server", 
            style="W.TButton", 
            cursor="hand2",
            command= lambda: self.event.ToggleServTrans()
        ).pack(side='right', pady=5)

        self.pack(fill="x", side="top")

        
        
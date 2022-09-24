from tkinter import *
from tkinter import ttk, colorchooser, filedialog
from ConfigHandler import getConfig, saveConfig
#import BindWindow
import StylingPage as StylP

class SettingsW(Frame):
    configDict = getConfig()
    settingsBool = False

    def __init__(self, parent):
        Frame.__init__(self, parent)
        self.parent = parent
        self.configure(background=self.configDict["frameBackground"])
        self.widgets()

    def widgets(self):
        self.settingsBtnLabel = Label(
            self, 
            text="Button Colors", 
            font=('helvetica', 16, "bold italic"), 
            background=self.configDict.get('frameBackground'), 
            foreground=self.configDict.get('labelForeground')
        ).pack()

        self.settingsBtnFontColor = ttk.Button(
            self, 
            text="Font Color", 
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: self.chooseColor("buttonForeground")
        ).pack()

        self.settingsBtnBgColor = ttk.Button(
            self, 
            text="Button BG", 
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: self.chooseColor("buttonBackground")
        ).pack()

        self.settingsLabelsLabel = Label(
            self, 
            text="Label Colors", 
            font=('helvetica', 16, "bold italic"), 
            background=self.configDict["frameBackground"], 
            foreground=self.configDict["labelForeground"]
        ).pack()

        self.settingsLabelColor = ttk.Button(
            self, 
            text="FG Color", 
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: self.chooseColor("labelForeground")
        ).pack()

        self.settingsBkgLabel = Label(
            self, 
            text="Background Color", 
            font=('helvetica', 16, "bold italic"), 
            background=self.configDict["frameBackground"], 
            foreground=self.configDict["labelForeground"]
        ).pack()

        self.settingsBgColor = ttk.Button(
            self, 
            text="Frame BG Color", 
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: self.chooseColor("frameBackground")
        ).pack()

        self.changeBgImageLabel = Label(
            self, 
            text="BG Image", 
            font=('helvetica', 16, "bold italic"), 
            background=self.configDict["frameBackground"], 
            foreground=self.configDict["labelForeground"]
        ).pack()

        self.settingsBgImage = ttk.Button(
            self, 
            text="Upload", 
            style="W.TButton", 
            cursor="hand2"
        ).pack()

        self.workDirLabel = Label(
            self, 
            text="DL Dir", 
            font=('helvetica', 16, "bold italic"), 
            background=self.configDict["frameBackground"], 
            foreground=self.configDict["labelForeground"]
        ).pack()

        self.workDirBtn = ttk.Button(
            self, 
            text="Dir", 
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: self.setWorkDir()
        ).pack()

        self.bindLabel = Label(
            self, 
            text="Keybinds", 
            font=('helvetica', 16, "bold italic"), 
            background=self.configDict["frameBackground"], 
            foreground=self.configDict["labelForeground"]
        ).pack()

        #self.bindBtn = ttk.Button(self, text="Bind", style="W.TButton", cursor="hand2", command= lambda: self.setKeyBinds()).pack()

    def setWorkDir(self):
        filename = filedialog.askdirectory()
        configDi = getConfig()
        configDi.update({'workDir': filename})
        saveConfig(configDi)

    def ToggleSettings(self):
        if self.settingsBool:
            self.pack_forget()
            self.settingsBool = False
        else:
            self.pack(side="right", anchor="ne")
            self.settingsBool = True

    def chooseColor(self, item):
        colorCode = colorchooser.askcolor(title ="Choose color")
        colorCodes = colorCode[1]
        configDict = getConfig()
        configDict.update({item: colorCodes})
        saveConfig(configDict)

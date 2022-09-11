from tkinter import *
from tkinter import ttk, colorchooser
from ConfigHandler import getConfig, saveConfig
import StylingPage as StylP

class SettingsW(Frame):
    configDict = getConfig()
    settingsBool = True

    def __init__(self, parent, controller):
        self.style = StylP.styler()
        Frame.__init__(self, parent)
        self.parent = parent
        self.configure(background=self.configDict.get('frameBackground'))
        self.widgets()
        self.toggleSettings()
    
    def widgets(self):
        self.settingsBtnLabel = Label(self, text="Button Colors", font=('helvetica', 16, "bold italic"), background=self.configDict.get('frameBackground'), foreground=self.configDict.get('labelForeground'))
        self.settingsBtnLabel.pack()

        self.settingsBtnFontColor = ttk.Button(self, text="Font Color", style="W.TButton", cursor="hand2", command= lambda: self.chooseColor("buttonForeground")).pack()
        self.settingsBtnBgColor = ttk.Button(self, text="Button BG", style="W.TButton", cursor="hand2", command= lambda: self.chooseColor("buttonBackground")).pack()

        self.settingsLabelsLabel = Label(self, text="Label Colors", font=('helvetica', 16, "bold italic"), background=self.configDict.get("frameBackground"), foreground=self.configDict.get("labelForeground"))
        self.settingsLabelsLabel.pack()

        self.settingsLabelColor = ttk.Button(self, text="FG Color", style="W.TButton", cursor="hand2", command= lambda: self.chooseColor("labelForeground")).pack()

        self.settingsBkgLabel = Label(self, text="Background Color", font=('helvetica', 16, "bold italic"), background=self.configDict.get("frameBackground"), foreground=self.configDict.get("labelForeground"))
        self.settingsBkgLabel.pack()

        self.settingsBgColor = ttk.Button(self, text="Frame BG Color", style="W.TButton", cursor="hand2", command= lambda: self.chooseColor("frameBackground")).pack()

        # self.changeBgImageLabel = Label(self, text="BG Image", font=('helvetica', 16, "bold italic"), background=self.configDict.get("frameBackground"), foreground=self.configDict.get("labelForeground"))
        # self.changeBgImageLabel.pack()

        # self.settingsBgImage = ttk.Button(self, text="Upload", style="W.TButton", cursor="hand2").pack()

    def toggleSettings(self):
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
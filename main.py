from ast import Break
import tkinter as tk
from tkinter import YES, Label, Tk, Frame
import os, signal, time
import threading
from PIL import ImageTk as ITK
from PIL import Image as PILImage
import SettingsPage as SP
import BannerPage as BP
import BottomPage as BotP
import ButtonPage as ButP
import ChatPage as CP
import StylingPage as StylP
from ConfigHandler import *

class MyApp(Tk):
    configDict = getConfig()

    def __init__(self, *args, **kwargs):
        self.chatUser = ''
        self.idList = []
        self.settingsShow = False
        self.chatShow = False

        Tk.__init__(self, *args, **kwargs)
        self.configure(background=self.configDict.get('frameBackground'))

        mainFrame = Frame(self, background=self.configDict.get('frameBackground'))
        mainFrame.pack(expand="true", fill="both")

        #Setting background image into mainFrame
        if self.configDict.get('bgImage') != "":
            bgImagePicked = self.configDict.get('bgImage')
            img = PILImage.open(bgImagePicked)
            imgResized = img.resize((1920, 1080), PILImage.ANTIALIAS)
            bgImage = ITK.PhotoImage(imgResized)
            bgImageLabel = Label(mainFrame, image=bgImage, background=self.configDict.get("frameBackground"))
            bgImageLabel.place(x=0, y=0)
            bgImageLabel.image = bgImage
        
        self.bannerFrame = BP.BannerF(mainFrame, self)
        self.bottomFrame = BotP.BottomF(mainFrame, self)
        self.buttonFrame = ButP.ButtonF(mainFrame, self)
        self.settingsFrame = SP.SettingsW(mainFrame, self)
        self.chatFrame = CP.ChatF(mainFrame, self)

    def shutdown(self):
        for i in self.idList:
            os.kill(i, signal.SIGTERM)
        root.destroy()
       
root = MyApp()

icon = "icon.ico"
root.iconbitmap(icon)
#root.state("zoomed")
root.geometry("1920x1080+0+0")
root.title("Dashboard")
root.resizable(True, True)
root.mainloop()

from tkinter import *
import BannerPage as BP
import os, signal
import SettingsPage as SP
import BottomPage as BotP
import ButtonPage as ButP
import ChatPage as CP
import StylingPage as StylP
from PIL import ImageTk as ITK
from PIL import Image as PILImage
from confighandler import *

class Event(object):
 
    def __init__(self):
        self.__eventhandlers = []
 
    def __iadd__(self, handler):
        self.__eventhandlers.append(handler)
        return self
 
    def __isub__(self, handler):
        self.__eventhandlers.remove(handler)
        return self
 
    def __call__(self, *args, **keywargs):
        for eventhandler in self.__eventhandlers:
            eventhandler(*args, **keywargs)
                 

     
    def StartAlarm(self):
        print ("Alarm has started")
         
class Events(object):
     
    def __init__(self):
        self.DownSize = Event()
        self.FullScreen = Event()
        self.Minimize = Event()
        self.OnLockBroken = Event()
        self.OnShutDown = Event()
        self.ToggleOpen = Event()
         
    def FireEvent(self):
        # This function will be executed once a lock is broken and will
        # raise an event
        self.DownSize()
        self.FullScreen()
        self.Minimize()
        self.OnLockBroken()
        self.OnShutDown()
        self.ToggleOpen()
        
        
    def AddSubscribersForLockBrokenEvent(self, objMethod):
        self.OnLockBroken += objMethod
         
    def RemoveSubscribersForLockBrokenEvent(self, objMethod):
        self.OnLockBroken -= objMethod
        
    def AddSubscribersForShutDownEvent(self, objMethod):
        self.OnShutDown += objMethod
         
    def RemoveSubscribersForShutDownEvent(self, objMethod):
        self.OnShutDown -= objMethod
        
    def AddSubscribersForToggleOpenEvent(self, objMethod):
        self.ToggleOpen += objMethod
         
    def RemoveSubscribersForToggleOpenEvent(self, objMethod):
        self.ToggleOpen -= objMethod
        
    def AddSubscribersForMinimizeEvent(self, objMethod):
        self.Minimize += objMethod
    
    def RemoveSubscribersForMinimizeEvent(self, objMethod):
        self.Minimize -= objMethod
        
    def AddSubscribersForDownSizeEvent(self,objMethod):
        self.DownSize += objMethod
         
    def RemoveSubscribersForDownSizeEvent(self,objMethod):
        self.DownSize -= objMethod
        
    def AddSubscribersForFullScreenEvent(self,objMethod):
        self.FullScreen += objMethod
         
    def RemoveSubscribersForFullScreenEvent(self,objMethod):
        self.FullScreen -= objMethod

class MainApp(Frame):
    def __init__(self, parent, config):
        self.configDict = config
        self.chatUser = ''
        self.settingsShow = False
        self.chatShow = False
        self.style = StylP.styler()
        Frame.__init__(self, parent)
        self.parent = parent
        self.configure(background=self.configDict.get('frameBackground'))
        self.mainWidgets()
        
    def mainWidgets(self):
        self.pack(expand="true", fill="both")
        
        if self.configDict.get('bgImage') != "":
            bgImagePicked = self.configDict.get('bgImage')
            img = PILImage.open(bgImagePicked)
            imgResized = img.resize((1920, 1080), PILImage.ANTIALIAS)
            bgImage = ITK.PhotoImage(imgResized)
            bgImageLabel = Label(self, image=bgImage, background=self.configDict.get("frameBackground"))
            bgImageLabel.place(x=0, y=0)
            bgImageLabel.image = bgImage

class MyApp(Tk):
    
    def __init__(self, *args, **kwargs):
        self.idList = []
        self.configDict = getConfig()
        Tk.__init__(self, *args, **kwargs)
        # self.configure(background=self.configDict.get('frameBackground'))
        self.widgets()
        
    def widgets(self):
        eventHandler = Events()
        
        
        self.mainFrame = MainApp(self, self.configDict)
        self.bannerFrame = BP.BannerF(self.mainFrame, eventHandler)
        
        self.bottomFrame = BotP.BottomF(self.mainFrame)
        self.buttonFrame = ButP.ButtonF(self.mainFrame)
        self.settingsFrame = SP.SettingsW(self.mainFrame)
        self.chatFrame = CP.ChatF(self.mainFrame)
        
        eventHandler.AddSubscribersForDownSizeEvent(self.DownSize)
        eventHandler.AddSubscribersForFullScreenEvent(self.FullScreen)
        eventHandler.AddSubscribersForMinimizeEvent(self.Minimize)
        eventHandler.AddSubscribersForToggleOpenEvent(self.chatFrame.ToggleChat)
        eventHandler.AddSubscribersForShutDownEvent(self.shutdown)
        eventHandler.AddSubscribersForLockBrokenEvent(self.settingsFrame.ToggleSettings)
     
    
    def Minimize(self): 
        self.state("icon")
        
    def FullScreen(self):
        self.wm_attributes("-fullscreen", True)
        
    def DownSize(self):
        self.wm_attributes("-fullscreen", False)
       
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

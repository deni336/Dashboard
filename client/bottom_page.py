from tkinter import *
from tkinter import ttk
from time import strftime

from client.config_handler import *

class BottomF(Frame):
    configDict = getConfig()
    def __init__(self, parent):
        Frame.__init__(self, parent)
        self.parent = parent
        self.configure(background=self.configDict.get('frameBackground'))
        self.widgets()
        
    def widgets(self):
        self.pack(side="bottom", fill="x")

        self.timeLabel = Label(
            self, 
            font=('helvetica', 16, "bold italic"), 
            background=self.configDict.get("frameBackground"), 
            foreground=self.configDict.get("labelForeground")
        )
        self.timeLabel.pack(side="bottom")

        self.myTime()
        
    def myTime(self):
        timeString = strftime('%d %b %y @ %H:%M:%S %p')
        self.timeLabel.config(text=timeString)
        self.timeLabel.after(1000, self.myTime)
        
        
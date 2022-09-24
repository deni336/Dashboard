import sys
from tkinter import *
from tkinter import ttk

from ConfigHandler import *

class ServTransF(Frame):
    configDict = getConfig()
    servTransBool = True

    def __init__(self, parent):
        self.user = loadUser()
        
        Frame.__init__(self, parent)
        self.parent = parent
        self.configure(background=self.configDict['frameBackground'])
        self.widgets()

    def widgets(self):
        self.transFrame = Frame(
            self, 
            background=self.configDict['frameBackground']
        )
        self.transFrame.pack(fill='y')

        testBtn = ttk.Button(
            self.transFrame,
            text="test",
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: sys.exit
        ).pack()

    def ToggleServ(self):
        if self.servTransBool:
            self.pack(side="right", fill="y")
            self.servTransBool = False
        else:
            self.pack_forget()
            self.servTransBool = True

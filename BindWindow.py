from tkinter import *
from tkinter import ttk
from ConfigHandler import getConfig, saveConfig, update
import ButtonPage

class BindW(Tk):
    configDict = getConfig()

    def __init__(self, *args, **kwargs):
        configDict = getConfig()

        Tk.__init__(self, *args, **kwargs)
        self.configure(background=self.configDict.get('frameBackground'))
        self.widgets()

    def widgets(self):
        
        topLabel = Label(self, text="Bind Your Keys", font=('helvetica', 16, "bold italic"), 
                        background=self.configDict.get('frameBackground'), 
                        foreground=self.configDict.get('labelForeground'))
        topLabel.pack(side="top")

        bindbtn = ttk.Button(self, text='Bind', style="W.TButton", cursor="hand2", command= lambda: self.createBind(bindbtn))
        bindbtn.pack()

    def createBind(self, key, bindTo):
        bindList = [key, bindTo]
        update('keyBinds', bindList)


root = BindW()

icon = "icon.ico"
root.iconbitmap(icon)
root.geometry("300x300+500+500")
#root.state('withdrawn')
root.title("KeyBinds")
root.resizable(0, 0)
root.mainloop()
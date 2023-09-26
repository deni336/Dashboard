from tkinter import *
from tkinter import ttk
from time import strftime

from client.config_handler import *

class BottomF(Frame):
    config_dict = get_config()
    def __init__(self, parent):
        Frame.__init__(self, parent)
        self.parent = parent
        self.configure(background=self.config_dict.get('frameBackground'))
        self.widgets()
        
    def widgets(self):
        self.pack(side="bottom", fill="x")

        self.time_label = Label(
            self, 
            font=('helvetica', 16, "bold italic"), 
            background=self.config_dict.get("frameBackground"), 
            foreground=self.config_dict.get("labelForeground")
        )
        self.time_label.pack(side="bottom")

        self.my_time()
        
    def my_time(self):
        time_string = strftime('%d %b %y @ %H:%M:%S %p')
        self.time_label.config(text=time_string)
        self.time_label.after(1000, self.my_time)
        
        
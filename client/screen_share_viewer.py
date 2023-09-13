from tkinter import *
from tkinter import ttk

from ConfigHandler import *
from ServerTransactionsPage import *

class GenWindow(Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title('Screen Viewer')
        self.geometry('800x800')
        self.widgets()

    def widgets(self):
        newFrame = Frame(self)
        newFrame.pack_propagate(0)
        # newFrame.pack(fill='both', expand='true')
        newFrame.grid_rowconfigure(0, weight=1)
        newFrame.grid_columnconfigure(0, weight=1)
        
        self.resizable(True, True)

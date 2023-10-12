from tkinter import *
from tkinter import ttk

from config_handler import *
from server_transactions_page import *

class GenWindow(Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title('Screen Viewer')
        self.geometry('800x800')
        self.widgets()

    def widgets(self):
        new_frame = Frame(self)
        new_frame.pack_propagate(0)
        # newFrame.pack(fill='both', expand='true')
        new_frame.grid_rowconfigure(0, weight=1)
        new_frame.grid_columnconfigure(0, weight=1)
        
        self.resizable(True, True)

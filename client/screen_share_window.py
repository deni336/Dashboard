from tkinter import *
from tkinter import ttk

from client.config_handler import *
from client.server_transactions_page import *

class ScreenShareW(Toplevel):
    config_dict = get_config()
    user_to_view = ServTransF.get_item

    def __init__(self, master = None):
        super().__init__(master = None)
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

    def open_window(self):
        pass



    
        

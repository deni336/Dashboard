import os
import signal
import tkinter as tk
from pathlib import Path
from PIL import Image as PILImage
from PIL import ImageTk as ITK

import client.banner_page as BP
import client.bottom_page as BotP
import client.button_page as ButP
import client.chat_page as CP
from client.config_handler import get_config
from client import File_Manager
import client.server_transactions_page as STP
import client.settings_page as SP

##### To Do's

## BUGS
# - config.json file does not update the config on my pc. It is somehow storing the old data and loading it over and over again.
#   Also I deleted my config.json file and it is still loading in a config somehow but it doesn't create one.

## Deni
# Server call for file list and broadcasting users list
# Update file list from server with refresh button
# Add front end for screen share connection
# Functionality for background image
# Client side for who is screen sharing
# Key Binds?
# refresh bg image
# get screen res from system

## gRPC

# connected users list
# 


class Event:
 
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

class Events:

    def __init__(self):
        self.down_size = Event()
        self.fullscreen = Event()
        self.minimize = Event()
        self.on_lock_broken = Event()
        self.on_shutdown = Event()
        self.toggle_open = Event()
        self.toggle_serv_trans = Event()
        self.update_background = Event()
        # self.update_messages = Event()
       

    def FireEvent(self):
        # This function will be executed once a lock is broken and will
        # raise an event
        self.down_size()
        self.fullscreen()
        self.minimize()
        self.on_lock_broken()
        self.on_shutdown()
        self.toggle_open()
        self.toggle_serv_trans()
        # self.UpdateMessages()


    def add_subscribers_for_lock_broken_event(self, obj_method):
        self.on_lock_broken += obj_method

    def remove_subscribers_for_lock_broken_event(self, obj_method):
        self.on_lock_broken -= obj_method

    def add_subscribers_for_shutdown_event(self, obj_method):
        self.on_shutdown += obj_method

    def remove_subscribers_for_shutdown_event(self, obj_method):
        self.on_shutdown -= obj_method

    def add_subscribers_for_toggle_open_event(self, obj_method):
        self.toggle_open += obj_method

    def remove_subscribers_for_toggle_open_event(self, obj_method):
        self.toggle_open -= obj_method

    def add_subscribers_for_toggle_serv_trans_event(self, obj_method):
        self.toggle_serv_trans += obj_method

    def remove_subscribers_for_toggle_serv_trans_event(self, obj_method):
        self.toggle_serv_trans -= obj_method

    def add_subscribers_for_minimize_event(self, obj_method):
        self.minimize += obj_method

    def remove_subscribers_for_minimize_event(self, obj_method):
        self.minimize -= obj_method

    def add_subscribers_for_down_size_event(self,obj_method):
        self.down_size += obj_method

    def remove_subscribers_for_down_size_event(self,obj_method):
        self.down_size -= obj_method

    def add_subscribers_for_fullscreen_event(self,obj_method):
        self.fullscreen += obj_method

    def remove_subscribers_for_fullscreen_event(self,obj_method):
        self.fullscreen -= obj_method

    def add_subscribers_for_update_background_event(self, obj_method):
        self.update_background += obj_method

    def remove_subscribers_for_update_background_event(self, obj_method):
        self.update_background -= obj_method


class MainApp(tk.Frame):
    def __init__(self, parent, config):
        super().__init__(parent)
        self.config_dict = config
        self.chat_user = ''
        self.settings_show = False
        self.chat_show = False
        self.serv_trans_show = False
        tk.Frame.__init__(self, parent)
        self.parent = parent
        self.configure(background=self.config_dict['frameBackground'])
        self.main_widgets()
        self.update_background()

    def main_widgets(self):
        self.pack(expand="true", fill="both")

    def update_background(self):
        try:
            img = PILImage.open(self.config_dict["bgImage"])
            img_resized = img.resize((1920, 1080), PILImage.Resampling.LANCZOS)
            bg_image = ITK.PhotoImage(img_resized)
            bg_image_label = tk.Label(
                self, 
                image=bg_image, 
                background=self.config_dict["frameBackground"]
            )
            bg_image_label.place(x=0, y=0)
            bg_image_label.image = bg_image
            MyApp.update(self)
        except tk.TclError as e:
            print(e)

class MyApp(tk):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.id_list = []
        self.config_dict = get_config()
        File_Manager.FileManager.whats_avail(File_Manager)
        tk.__init__(self, *args, **kwargs)
        self.widgets()

    def initialize_widgets(self):
        event_handler = Events()

        self.main_frame = MainApp(self, self.config_dict)
        self.banner_frame = BP.Banner(self.main_frame, event_handler)
        self.bottom_frame = BotP.BottomF(self.main_frame)
        self.button_frame = ButP.ButtonF(self.main_frame)
        self.settings_frame = SP.SettingsW(self.main_frame, event_handler)
        self.chat_frame = CP.ChatF(self.main_frame)
        self.serv_frame = STP.ServTransF(self.main_frame)

        event_handler.add_subscribers_for_down_size_event(self.down_size)
        event_handler.add_subscribers_for_fullscreen_event(self.fullscreen)
        event_handler.add_subscribers_for_minimize_event(self.minimize)
        event_handler.add_subscribers_for_toggle_open_event(self.chat_frame.ToggleChat)
        event_handler.add_subscribers_for_shutdown_event(self.shutdown)
        event_handler.add_subscribers_for_lock_broken_event(self.settings_frame.ToggleSettings)
        event_handler.add_subscribers_for_toggle_serv_trans_event(self.serv_frame.ToggleServ)
        event_handler.add_subscribers_for_update_background_event(MainApp.update_background)


    def minimize(self): 
        self.state("icon")

    def fullscreen(self):
        self.wm_attributes("-fullscreen", True)

    def down_size(self):
        self.wm_attributes("-fullscreen", False)

    def shutdown(self):
        for i in CP.ChatF.id_list:
            os.kill(i, signal.SIGTERM)
        root.destroy()

root = MyApp()

icon = Path.cwd().joinpath("./client/icon.ico")
root.iconbitmap(icon)
#root.state("zoomed")
root.geometry("1920x1080+0+0")
root.title("Dashboard")
root.resizable(True, True)
root.mainloop()

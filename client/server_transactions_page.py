import os, signal, sys, time
from tkinter import *
from tkinter import ttk
import socket
import subprocess
import webbrowser

from client.config_handler import *
#import ServerTransactionHandler as STH

class ServTransF(Frame):
    config_dict = get_config()
    serv_trans_bool = True
    get_item = []
    def __init__(self, parent):
        self.user = load_user()
        
        Frame.__init__(self, parent)
        self.parent = parent
        self.configure(background=self.config_dict['frameBackground'])
        self.widgets()

    def widgets(self):
        self.trans_frame = Frame(
            self, 
            background=self.config_dict['frameBackground']
        )
        self.trans_frame.pack()

        screen_share_label = Label(
            self.trans_frame,
            text="Screen Sharing",
            background=self.config_dict["frameBackground"], 
            foreground=self.config_dict["labelForeground"], 
            font=("American typewriter", 20)
        ).pack()

        columns = ('Users')
        self.share_tree = ttk.Treeview(
            self.trans_frame,
            columns=columns,
            show='headings'
        )
        self.share_tree.heading('Users', text="Users")
        self.share_tree.pack(fill='x')

        refresh_btn = ttk.Button(
            self.trans_frame,
            text="Refresh",
            style="W.TButton",
            command= lambda: self.update_share_tree()
        ).pack(side='right')

        disconnect_btn = ttk.Button(
            self.trans_frame,
            text="Disco",
            style="W.TButton",
            command= lambda: self.kill_share_screen()
        ).pack(side='right')

        share_screen_btn = ttk.Button(
            self.trans_frame,
            text="Share",
            style="W.TButton",
            command= lambda: self.fire_screen_share()
        ).pack(side='right')

        view_btn = ttk.Button(
            self.trans_frame,
            text="View",
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: self.view_selected_screen()
        ).pack(side='right')

    def update_share_tree(self):
        x = self.share_tree.get_children()
        for i in x:
            self.share_tree.delete(i)
        self.share_tree.insert()

    def kill_share_screen(self):
        subprocess.Popen(
                [
                    'C:\Program Files\Google\Chrome\Application\chrome.exe', 
                    self.myIp[0] + ':' + '7070/stop-sharing'
                ]
            )
        
    def view_selected_screen(self):
        focus_item = self.share_tree.focus()
        f_item = self.share_tree.item(focus_item)
        self.get_item = f_item.get('values')
        self.event.open_screen_share()


    def fire_screen_share(self):
        self.myIp = self.config_dict['clientIp']
        try:
            subprocess.Popen(
                [
                    'C:\Program Files\Google\Chrome\Application\chrome.exe',  
                    self.myIp[0] + ':' + '7070/start-sharing'
                ]
            )
        except:
            subprocess.Popen(
                [
                    'C:\Program Files (x86)\Google\Chrome\Application/chrome.exe', 
                    self.myIp[0] + ':' + '7070/start-sharing'
                ]
            )

    def ToggleServ(self):
        if self.serv_trans_bool:
            self.pack(side="right", anchor='ne')
            self.serv_trans_bool = False
        else:
            self.pack_forget()
            self.serv_trans_bool = True

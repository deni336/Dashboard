import os, signal, sys, time
from tkinter import *
from tkinter import ttk
import socket
import subprocess
import webbrowser

from client.ConfigHandler import *
#import ServerTransactionHandler as STH

class ServTransF(Frame):
    configDict = getConfig()
    servTransBool = True
    getItem = []
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
        self.transFrame.pack()

        screenShareLabel = Label(
            self.transFrame,
            text="Screen Sharing",
            background=self.configDict["frameBackground"], 
            foreground=self.configDict["labelForeground"], 
            font=("American typewriter", 20)
        ).pack()

        columns = ('Users')
        self.shareTree = ttk.Treeview(
            self.transFrame,
            columns=columns,
            show='headings'
        )
        self.shareTree.heading('Users', text="Users")
        self.shareTree.pack(fill='x')

        refreshBtn = ttk.Button(
            self.transFrame,
            text="Refresh",
            style="W.TButton",
            command= lambda: self.updateShareTree()
        ).pack(side='right')

        disconnectBtn = ttk.Button(
            self.transFrame,
            text="Disco",
            style="W.TButton",
            command= lambda: self.killShareScreen()
        ).pack(side='right')

        shareScreenBtn = ttk.Button(
            self.transFrame,
            text="Share",
            style="W.TButton",
            command= lambda: self.fireScreenShare()
        ).pack(side='right')

        viewBtn = ttk.Button(
            self.transFrame,
            text="View",
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: self.viewSelectedScreen()
        ).pack(side='right')

    def updateShareTree(self):
        x = self.shareTree.get_children()
        for i in x:
            self.shareTree.delete(i)
        self.shareTree.insert()

    def killShareScreen(self):
        subprocess.Popen(
                [
                    'C:\Program Files\Google\Chrome\Application\chrome.exe', 
                    self.myIp[0] + ':' + '7070/stop-sharing'
                ]
            )
        
    def viewSelectedScreen(self):
        focusItem = self.shareTree.focus()
        fItem = self.shareTree.item(focusItem)
        self.getItem = fItem.get('values')
        self.event.OpenScreenShare()


    def fireScreenShare(self):
        self.myIp = self.configDict['clientIp']
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
        if self.servTransBool:
            self.pack(side="right", anchor='ne')
            self.servTransBool = False
        else:
            self.pack_forget()
            self.servTransBool = True

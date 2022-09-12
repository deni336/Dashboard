from tkinter import *
from tkinter import ttk
from tkinter import filedialog
import tkinter
from ConfigHandler import *
import ChatClient
import threading, sys
import FileManager
import os

class ChatF(Frame):
    configDict = getConfig()
    chatBool = True
    idList = []

    def __init__(self, parent):
        
        self.user = loadUser()
        self.connection = []
        Frame.__init__(self, parent)
        self.parent = parent
        self.configure(background=self.configDict.get('frameBackground'))
        self.servConn()
        self.widgets()
        self.treeLoop()
        
        
    
    def widgets(self):
        inputUser1 = StringVar()
        messageInput = StringVar()
        nameInputBox = Entry(self, textvariable=inputUser1, background=self.configDict.get("frameBackground"), foreground=self.configDict.get('buttonForeground'), font=('American typewriter', 12, 'bold'))
        nameInputBox.pack(side="top", pady=5)
        
        def enterPressed1(self):
            self.user = inputUser1.get()
            self.nameInputBox.config(state=DISABLED)
            update("user", self.user)
    
    
        if self.configDict.get('user') != "":
            self.user = self.configDict.get('user')
            nameInputBox.config(state=DISABLED)
            inputUser1.set(self.user)
        else:
            self.nameInputBox.config(state=NORMAL)
            inputUser1.set('Enter your name')
            
        nameInputBox.bind("<Return>", enterPressed1)
        
        self.messagesFrame = Frame(self, background=self.configDict.get("frameBackground"))
        self.messagesFrame.pack()
        
        self.scroll = Scrollbar(self.messagesFrame, orient="vertical", jump=True)
        self.scroll.pack(side="right", fill='y', pady=2)
        
        messages = Text(self.messagesFrame, background=self.configDict.get("frameBackground"), foreground=self.configDict.get('buttonForeground'), font=('American typewriter', 12, 'bold'), width=45, height=30, yscrollcommand=self.scroll.set)
        messages.pack(padx=5, pady=2, side="left")
        self.scroll.configure(command=messages.yview)
        
        if self.connection[1] != '':
            messages.config(state=NORMAL)
            messages.insert(END, self.connection[1])
            messages.config(state=DISABLED)
            

        self.inputField = Entry(self, textvariable=messageInput, cursor="xterm",insertbackground="red", background=self.configDict.get("frameBackground"), foreground=self.configDict.get('buttonForeground'), font=('American typewriter', 12, 'bold'))
        self.inputField.pack(fill="x", padx=5, pady=2)
    

        def enterPressed(self):
            inputGet = messageInput.get()
            ChatClient.ChatClient.sendMessage(inputGet)
            messageInput.set('')
            messages.see("end")
        
        self.inputField.bind("<Return>", enterPressed)
        
        def messageUpdater():
            try:
                response = ChatClient.ChatClient.recMessage()
                print(response)
                messages.config(state=NORMAL)
                messages.insert(END, response)
                messages.config(state=DISABLED)
                messageUpdater()
            except:
                pass
        
        try:
            messageUpdateThread = threading.Thread(target=messageUpdater)
            messageUpdateThread.start() 
            a = os.getpid()
            self.idList.append(a)
        except (KeyboardInterrupt, SystemExit):
            sys.exit()

    def treeLoop(self):
        treeFrame = Frame(self, background=self.configDict.get("frameBackground"))
        treeFrame.pack(fill='both')

        tv1 = ttk.Treeview(treeFrame)
        columnList = ['User','Filename', 'Path']
        tv1['columns'] = columnList
        tv1['show'] = "headings"
        for column in columnList:
            tv1.heading(column, text=column)
            tv1.column(column, width=135)
        tv1.pack(side='left', fill='x', anchor='n', padx=5)
        treeScrollY = Scrollbar(treeFrame)
        treeScrollY.configure(command=tv1.yview)
        tv1.configure(yscrollcomman=treeScrollY.set)
        treeScrollY.pack(side='right', fill='y')

        self.stageBtn = ttk.Button(self, text="Stage", style="W.TButton", cursor="hand2", command= lambda: stageMeth(self))
        self.stageBtn.pack(side='left', anchor='nw', padx=5, pady=5)

        self.deleteBtn = ttk.Button(self, text="Delete", style="W.TButton", cursor="hand2", command= lambda: delMeth(self))
        self.deleteBtn.pack(side='left', anchor='n', padx=5, pady=5)
        
        self.refreshBtn = ttk.Button(self, text="Refresh", style="W.TButton", cursor="hand2", command= lambda: tv1LoadData(self))
        self.refreshBtn.pack(side='left', anchor='n', padx=5, pady=5)

        self.downloadBtn = ttk.Button(self, text="Download", style="W.TButton", cursor="hand2", command= lambda: FileManager.FileManager.download())
        self.downloadBtn.pack(side='left', anchor='ne', padx=5, pady=5)

        def delMeth(self):
            focusItem = tv1.focus()
            fItem = tv1.item(focusItem)
            delItem = fItem.get('values')
            FileManager.FileManager.delete(FileManager.FileManager, delItem[2])
            tv1LoadData(self)

        def stageMeth(self):
            filename = filedialog.askdirectory()
            FileManager.FileManager.stage(FileManager.FileManager, filename)
            tv1LoadData(self)

        def tv1LoadData(self):
            configDi = getConfig()
            tv1ClearData()
            download = configDi.get('download')
            for i in download:
                tv1.insert("", "end", values=(self.user, os.path.basename(i), i))

        def tv1ClearData():
            x = tv1.get_children()
            for i in x:
                tv1.detach(*i)
        
        tv1LoadData(self)
        
    def servConn(self):
        self.connection = ChatClient.ChatClient.ServerConnection(self.user)
        self.idList.append(self.connection[0])
        
            
    def ToggleChat(self):
        if self.chatBool:
            self.pack(side="right", fill="y")
            self.chatBool = False
        else:
            self.pack_forget()
            self.chatBool = True

 #Connecting to the server
# Get-Process -Id (Get-NetTCPConnection -LocalPort 6969).OwningProcess
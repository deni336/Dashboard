from tkinter import *
from ConfigHandler import *
import chatclient
import threading, sys
import StylingPage
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
            

        self.inputField = Entry(self, textvariable=messageInput, cursor="fleur",insertbackground="red", background=self.configDict.get("frameBackground"), foreground=self.configDict.get('buttonForeground'), font=('American typewriter', 12, 'bold'))
        self.inputField.pack(fill="x", padx=5, pady=2)
        
        def enterPressed(self):
            inputGet = messageInput.get()
            chatclient.ChatClient.sendMessage(inputGet)
            messageInput.set('')
            messages.see("end")
        
        self.inputField.bind("<Return>", enterPressed)
        
        def messageUpdater():
            try:
                response = chatclient.ChatClient.recMessage()
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
        
        
            
    def servConn(self):
        self.connection = chatclient.ChatClient.ServerConnection(self.user, "192.168.45.10")
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
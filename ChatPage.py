from tkinter import *
from tkinter import ttk
from ConfigHandler import *
from time import strftime
from ChatClient import *
import threading, sys
import StylingPage

class ChatF(Frame):
    configDict = getConfig()
    chatBool = True
    
    def __init__(self, parent, controller):
        self.idList = []
        self.user = os.getlogin()
        self.style = StylingPage.styler()
        Frame.__init__(self, parent)
        self.parent = parent
        self.configure(background=self.configDict.get('frameBackground'))
        self.toggleChat()
        self.widgets()
        
    def widgets(self):
        def enterPressed(event):
            inputGet = self.inputField.get()
            ChatClient.sendMessage(inputGet)
            self.messageInput.set('')
            self.messages.see("end")
            return "break"
        def servConn():
            b = ChatClient.serverConnection(self.user, self.chatUser)
            self.idList.append(b[0])
            if b[1] != '':
                self.messages.config(state=NORMAL)
                self.messages.insert(END, b[1])
                self.messages.config(state=DISABLED)

        def enterPressed1(event):
            self.chatUser = self.usernameInput.get()
            self.usernameInput.config(state=DISABLED)
            update("user", self.chatUser)
        
        def comms():
            if self.configDict.get('user') != "":
                self.chatUser = self.configDict.get('user')
                self.usernameInput.config(state=DISABLED)
                self.inputUser1.set(self.chatUser)
            else:
                self.usernameInput.config(state=NORMAL)
                self.inputUser1.set('Enter your name')
        
        def messageUpdater():
            try:
                response = ChatClient.recMessage()
                print(response)
                self.messages.config(state=NORMAL)
                self.messages.insert(END, response)
                self.messages.config(state=DISABLED)
                messageUpdater()
            except:
                pass
        
        self.inputUser1 = StringVar()
        self.usernameInput = Entry(self, text=self.inputUser1, background=self.configDict.get("frameBackground"), foreground=self.configDict.get('buttonForeground'), font=('American typewriter', 12, 'bold'))
        self.usernameInput.pack(side="top", pady=5)
        self.usernameInput.bind("<Return>", enterPressed1)
            
        self.messageInput = StringVar()

        self.messagesFrame = Frame(self, background=self.configDict.get("frameBackground"))
        self.messagesFrame.pack()
        self.scroll = Scrollbar(self.messagesFrame, orient="vertical", jump=True)
        self.scroll.pack(side="right", fill='y', pady=2)
        self.messages = Text(self.messagesFrame, background=self.configDict.get("frameBackground"), foreground=self.configDict.get('buttonForeground'), font=('American typewriter', 12, 'bold'), width=45, height=30, yscrollcommand=self.scroll.set)
        self.messages.pack(padx=5, pady=2, side="left")
        self.scroll.configure(command=self.messages.yview)

        self.inputField = Entry(self, text=self.messageInput, background=self.configDict.get("frameBackground"), foreground=self.configDict.get('buttonForeground'), font=('American typewriter', 12, 'bold'))
        self.inputField.pack(fill="x", padx=5, pady=2)
        self.inputField.bind("<Return>", enterPressed)

        try:
            messageUpdateThread = threading.Thread(target=messageUpdater)
            messageUpdateThread.start() 
            a = os.getpid()
            self.idList.append(a)
        except (KeyboardInterrupt, SystemExit):
            sys.exit()
        
        comms()
        servConn()

    def toggleBool(self):
        if self.chatBool:
            self.chatBool = False
            ChatF.toggleChat(self)
        else:
            self.chatBool = True
            ChatF.toggleChat(self)
    def toggleChat(self):
        if self.chatBool:
            self.pack(side="right", fill="y")
            self.chatBool = False
        else:
            self.pack_forget()
            self.chatBool = True

 #Connecting to the server
# Get-Process -Id (Get-NetTCPConnection -LocalPort 6969).OwningProcess
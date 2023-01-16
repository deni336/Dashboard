import os, socket
import threading, sys
from tkinter import *
from tkinter import filedialog, ttk
import protos.kasugai_pb2 as kasugaipy_pb2
import protos.kasugai_pb2_grpc as kasugaipy_pb2_grpc

import ChatClient
import ChatHistory
import ChatPopOut
from ConfigHandler import *
import FileManager



class ChatF(Frame):
    configDict = getConfig()
    chatBool = True
    idList = []
    
    def __init__(self, parent):
        self.user = loadUser()
        self.connection = ChatClient.ChatClient()
        self.broadcast = ""
        self.msg_response = "test"
        Frame.__init__(self, parent)
        self.parent = parent
        self.configure(background=self.configDict['frameBackground'])
        self.servConn()
        self.treeLoop()
       
    def treeLoop(self):
        messageInput = StringVar()
        self.additionalButtons = Frame(
            self,
            background=self.configDict["frameBackground"]
        )
        self.additionalButtons.pack()

        self.viewCurrent = ttk.Button(
            self.additionalButtons,
            text="Current",
            style="W.TButton",
            cursor="hand2",
            command= lambda: self.tv1LoadData()
        ).pack(side='left')

        self.viewHist = ttk.Button(
            self.additionalButtons,
            text="History",
            style="W.TButton",
            cursor="hand2",
            command= lambda: self.tv1LoadHist()
        ).pack(side='left')

        self.popOut = ttk.Button(
            self.additionalButtons,
            text="Pop out",
            style="W.TButton",
            cursor="hand2",
            command= lambda: ChatPopOut.ChatF()
        ).pack(side='right')

        self.messagesFrame = Frame(
            self, 
            background=self.configDict["frameBackground"]
        )
        self.messagesFrame.pack()

        self.scroll = Scrollbar(
            self.messagesFrame, 
            orient="vertical", 
            jump=True
        )
        self.scroll.pack(side="right", fill='y', pady=2)

        messages = Text(
            self.messagesFrame, 
            background=self.configDict["frameBackground"], 
            foreground=self.configDict['buttonForeground'], 
            font=('American typewriter', 12, 'bold'), 
            width=45, 
            height=30, 
            yscrollcommand=self.scroll.set
        )
        messages.pack(padx=5, pady=2, side="left")

        self.scroll.configure(command=messages.yview)

        if self.connection != '':
            messages.config(state=NORMAL)
            messages.insert(END, self.connection.addr)
            messages.config(state=DISABLED)


        self.inputField = Entry(
            self, 
            textvariable=messageInput, 
            cursor="xterm",
            insertbackground="red", 
            background=self.configDict["frameBackground"], 
            foreground=self.configDict['buttonForeground'], 
            font=('American typewriter', 12, 'bold')
        )
        self.inputField.pack(fill="x", padx=5, pady=2)

        def enterPressed():
            inputGet = messageInput.get()
            # run(protoDict[0], inputGet)
            messageInput.set('')
            messages.see("end")

        self.inputField.bind("<Return>", enterPressed)

        def messageUpdater():
            try:
                response = self.broadcast
                print(response)
                messages.config(state=NORMAL)
                messages.insert(END, response)
                messages.config(state=DISABLED)
                ChatHistory.DatabaseManipulation.addMessage(response)
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

        treeFrame = Frame(
            self, 
            background=self.configDict["frameBackground"]
        )
        treeFrame.pack(fill='both')

        self.tv1 = ttk.Treeview(treeFrame)
        columnList = ['User','Filename', 'Size', 'Path']
        self.tv1['columns'] = columnList
        self.tv1['show'] = "headings"
        for column in columnList:
            self.tv1.heading(column, text=column)
            self.tv1.column(column, width=103)
        self.tv1.pack(side='left', fill='x', anchor='n', padx=5)
        treeScrollY = Scrollbar(treeFrame)
        treeScrollY.configure(command=self.tv1.yview)
        self.tv1.configure(yscrollcomman=treeScrollY.set)
        treeScrollY.pack(side='right', fill='y')

        self.stageBtn = ttk.Button(
            self, 
            text="Stage", 
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: stageMeth(self)
        ).pack(side='left', anchor='nw', padx=5, pady=5)

        self.deleteBtn = ttk.Button(
            self, 
            text="Delete", 
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: delMeth(self)
        ).pack(side='left', anchor='n', padx=5, pady=5)

        self.refreshBtn = ttk.Button(
            self, 
            text="Refresh", 
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: tv1LoadData(self)
        ).pack(side='left', anchor='n', padx=5, pady=5)

        self.downloadBtn = ttk.Button(
            self, 
            text="Download", 
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: download(self)
        ).pack(side='left', anchor='ne', padx=5, pady=5)

        def delMeth(self):
            focusItem = self.tv1.focus()
            fItem = self.tv1.item(focusItem)
            delItem = fItem.get('values')
            ip = socket.socket.getsockname(ChatClient.server)
            FileManager.FileManager.delete(FileManager.FileManager, [delItem[3], ip[0], delItem[2] ])
            tv1LoadData(self)

        def stageMeth(self):
            filename = filedialog.askdirectory()
            size = os.path.getsize(filename)
            ip = socket.socket.getsockname(ChatClient.server)
            FileManager.FileManager.stage(FileManager.FileManager, filename, ip[0], size)
            tv1LoadData(self)

        def download(self):
            focusItem = self.tv1.focus()
        #     fItem = self.tv1.item(focusItem)
        #     getItem = fItem.get('values')
        #     ip = ChatClient.ChatClient.dictOfUsers()
        #     FileClient.FileSender.connection(FileClient.FileSender, ip)
        #     FileClient.FileSender.sendingFile(getItem[0], getItem[2], getItem[3])


        def tv1LoadData(self):
            configDi = getConfig()
            #servList = ChatClient.ChatClient.listCall()
            tv1ClearData()
            download = configDi.get('download')
            if download != []:
                dnlsize = download[0]
                size = os.path.getsize(dnlsize[0])
                for i in download:
                    self.tv1.insert("", "end", values=(self.user, os.path.basename(i[0]), size, i[0]))
            # elif servList != []:
            #     for i in servList:
            #         self.tv1.insert("", "end", values=(i[3], os.path.basename(i[0]), size, i[0]))
            else:
                return

        def tv1LoadHist(self):
            tv1ClearData()
            messageList = ChatHistory.DatabaseManipulation.viewMessages()
            for message in messageList:
                self.tv1.insert("", "end", values=message)


        def tv1ClearData():
            x = self.tv1.get_children()
            for i in x:
                self.tv1.delete(i)

        tv1LoadData(self)
        
    def make_message(self, message):
        return kasugaipy_pb2.MessageResponse(
            message=message
        )
        
    def recv_messages(self):
        messages = [self.make_message(self.msg_response),]       
        for msg in messages:
            print("Sending message to server %s" % msg.message)
            self.broadcast = msg.message
            yield msg
                   
    # Example to get server connection working
    def servConn(self):
            self.connection.stub = kasugaipy_pb2_grpc.BroadcastStub(self.connection.channel)
            messages = self.connection.stub.ChatService(self.recv_messages())
            for msg in messages:
                print("R[{}] {}".format(msg.message, msg.timestamp))
        
        
    def ToggleChat(self):
        if self.chatBool:
            self.pack(side="right", anchor='ne')
            self.chatBool = False
        else:
            self.pack_forget()
            self.chatBool = True

 #Connecting to the server
# Get-Process -Id (Get-NetTCPConnection -LocalPort 6969).OwningProcess


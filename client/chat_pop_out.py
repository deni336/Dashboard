import os, socket
import threading, sys
from tkinter import *
from tkinter import filedialog, ttk

import client.chat_client as chat_client
import client.chat_history as chat_history
from client.config_handler import *
import client.File_Manager as File_Manager
import client.styling_page as styling_page


class ChatF(Tk):
    config_dict = get_config()
    idList = []

    def __init__(self):
        self.user = load_user()
        self.connection = []
        self.style = styling_page.styler()
        
        Tk.__init__(self)
        self.configure(background=self.config_dict['frameBackground'])
        self.serv_conn()
        self.widgets()
        self.tree_loop()

    def widgets(self):
        self.title('Dashboard')

    def tree_loop(self):
        message_input = StringVar()
        self.additional_buttons = Frame(
            self,
            background=self.config_dict["frameBackground"]
        )
        self.additional_buttons.pack()

        self.view_current = ttk.Button(
            self.additional_buttons,
            text="Current",
            style="W.TButton",
            cursor="hand2",
            command= lambda: self.tv1_load_data()
        ).pack(side='left')

        self.view_hist = ttk.Button(
            self.additional_buttons,
            text="History",
            style="W.TButton",
            cursor="hand2",
            command= lambda: self.tv1_load_hist()
        ).pack(side='right')

        # self.popOut = ttk.Button(
        #     self.additionalButtons,
        #     text="Pop out",
        #     style="W.TButton",
        #     cursor="hand2"

        # ).pack(side='right')

        self.messages_frame = Frame(
            self, 
            background=self.config_dict["frameBackground"]
        )
        self.messages_frame.pack()

        self.scroll = Scrollbar(
            self.messages_frame, 
            orient="vertical", 
            jump=True
        )
        self.scroll.pack(side="right", fill='y', pady=2)

        messages = Text(
            self.messages_frame, 
            background=self.config_dict["frameBackground"], 
            foreground=self.config_dict['buttonForeground'], 
            font=('American typewriter', 12, 'bold'), 
            width=45, 
            height=30, 
            yscrollcommand=self.scroll.set
        )
        messages.pack(padx=5, pady=2, side="left")

        self.scroll.configure(command=messages.yview)

        if self.connection != '':
            messages.config(state=NORMAL)
            messages.insert(END, self.connection[1])
            messages.config(state=DISABLED)


        self.input_field = Entry(
            self, 
            textvariable=message_input, 
            cursor="xterm",
            insertbackground="red", 
            background=self.config_dict["frameBackground"], 
            foreground=self.config_dict['buttonForeground'], 
            font=('American typewriter', 12, 'bold')
        )
        self.input_field.pack(fill="x", padx=5, pady=2)

        def enter_pressed(self):
            input_get = message_input.get()
            #run(protoDict[0], inputGet)
            message_input.set('')
            messages.see("end")

        self.input_field.bind("<Return>", enter_pressed)

        def message_updater():
            try:
                response = chat_client.chat_client.rec_message(chat_client.chat_client)
                print(response)
                messages.config(state=NORMAL)
                messages.insert(END, response)
                messages.config(state=DISABLED)
                message_updater()
            except:
                pass

        try:
            message_update_thread = threading.Thread(target=message_updater)
            message_update_thread.start() 
            a = os.getpid()
            self.idList.append(a)
        except (KeyboardInterrupt, SystemExit):
            sys.exit()

        tree_frame = Frame(
            self, 
            background=self.config_dict["frameBackground"]
        )
        tree_frame.pack(fill='both')

        self.tv1 = ttk.Treeview(tree_frame)
        column_list = ['User','Filename', 'Size', 'Path']
        self.tv1['columns'] = column_list
        self.tv1['show'] = "headings"
        for column in column_list:
            self.tv1.heading(column, text=column)
            self.tv1.column(column, width=103)
        self.tv1.pack(side='left', fill='x', anchor='n', padx=5)
        tree_scroll_y = Scrollbar(tree_frame)
        tree_scroll_y.configure(command=self.tv1.yview)
        self.tv1.configure(yscrollcomman=tree_scroll_y.set)
        tree_scroll_y.pack(side='right', fill='y')

        self.stage_btn = ttk.Button(
            self, 
            text="Stage", 
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: stage_meth(self)
        ).pack(side='left', anchor='nw', padx=5, pady=5)

        self.delete_btn = ttk.Button(
            self, 
            text="Delete", 
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: del_meth(self)
        ).pack(side='left', anchor='n', padx=5, pady=5)

        self.refresh_btn = ttk.Button(
            self, 
            text="Refresh", 
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: tv1_load_data(self)
        ).pack(side='left', anchor='n', padx=5, pady=5)

        self.download_btn = ttk.Button(
            self, 
            text="Download", 
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: download(self)
        ).pack(side='left', anchor='ne', padx=5, pady=5)

        def del_meth(self):
            focus_item = self.tv1.focus()
            f_item = self.tv1.item(focus_item)
            del_item = f_item.get('values')
            ip = socket.socket.getsockname(chat_client.server)
            File_Manager.FileManager.delete(File_Manager.FileManager, [del_item[3], ip[0], del_item[2] ])
            tv1_load_data(self)

        def stage_meth(self):
            filename = filedialog.askdirectory()
            size = os.path.getsize(filename)
            ip = socket.socket.getsockname(chat_client.server)
            File_Manager.FileManager.stage(File_Manager.FileManager, filename, ip[0], size)
            tv1_load_data(self)

        def download(self):
            focusItem = self.tv1.focus()
        #     fItem = self.tv1.item(focusItem)
        #     getItem = fItem.get('values')
        #     ip = ChatClient.ChatClient.dictOfUsers()
        #     FileClient.FileSender.connection(FileClient.FileSender, ip)
        #     FileClient.FileSender.sendingFile(getItem[0], getItem[2], getItem[3])


        def tv1_load_data(self):
            config_di = get_config()
            #servList = ChatClient.ChatClient.listCall()
            tv1_clear_data()
            download = config_di.get('download')
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

        def tv1_load_hist(self):
            tv1_clear_data()
            message_list = chat_history.DatabaseManipulation.view_messages()
            for message in message_list:
                self.tv1.insert("", "end", values=message)


        def tv1_clear_data():
            x = self.tv1.get_children()
            for i in x:
                self.tv1.delete(i)

        tv1_load_data(self)

    def serv_conn(self):
        self.connection = chat_client.ChatClient.ServerConnection(self.user)
        # ServerTransactionHandler.ServerTransactionHandler.checkIp(ServerTransactionHandler)

 #Connecting to the server
# Get-Process -Id (Get-NetTCPConnection -LocalPort 6969).OwningProcess
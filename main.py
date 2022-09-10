import tkinter as tk
from tkinter import *
from tkinter import ttk, colorchooser
import os, time, sys, signal
from time import sleep, strftime
import webbrowser
import subprocess
from PIL import ImageTk, Image
import confighandler
import chatclient
import threading



class MyApp(tk.Tk):
    
    def __init__(self):
        self.chatUser = ''
        self.configDict = {}
        self.idList = []
        tk.Tk.__init__(self)
        
        #Setting Background frame
        mainFrame = tk.Frame(self, bg=self.configDict.get("frameBackground"))
        mainFrame.pack(expand="1", fill="both")

        
        self.configDict = confighandler.getConfig()
        

        #MyApp.wm_attributes("-fullscreen", self.configDict.get('windowMode'))

        #Setting background image into mainFrame
        if self.configDict.get('bgImage') != "":
            bgImagePicked = self.configDict.get('bgImage')
            img = Image.open(bgImagePicked)
            imgResized = img.resize((1920, 1080), Image.ANTIALIAS)
            bgImage = ImageTk.PhotoImage(imgResized)
            bgImageLabel = tk.Label(mainFrame, image=bgImage, background=self.configDict.get("frameBackground"))
            bgImageLabel.place(x=0, y=0)
            bgImageLabel.image = bgImage

        #Creating Style variable to be used in buttons
        style = ttk.Style()
        style.theme_use('default')
        style.configure('W.TButton', foreground=self.configDict.get('buttonForeground'), background=self.configDict.get('buttonBackground'), fill="both", borderwidth="5", relief="ridge", font=
                        (self.configDict.get('buttonFont'), self.configDict.get("buttonFontsize"), self.configDict.get("buttonFontadd")))

        #Frame for the top of page to house appLabel, exitBtn, minimizeBtn, downsizeBtn, and maximizeBtn
        bannerFrame = tk.Frame(mainFrame, background=self.configDict.get("frameBackground"))
        bannerFrame.pack(fill="x")

        appLabel = ttk.Label(bannerFrame, text="Kasugai", background=self.configDict.get("frameBackground"), foreground=self.configDict.get("labelForeground"), font=("American typewriter", 25))
        appLabel.pack(side="left")

        def shutdown():
            for i in self.idList:
                os.kill(i, signal.SIGTERM)
            root.destroy()

        exitBtn = ttk.Button(bannerFrame, text="Exit", style="W.TButton", cursor="hand2",
                            command= lambda: shutdown())
        exitBtn.pack(side="right")

        minimizeBtn = ttk.Button(bannerFrame, text="Minimize", style="W.TButton", cursor="hand2", command= lambda: root.state("icon"))
        minimizeBtn.pack(side="right")

        downsizeBtn = ttk.Button(bannerFrame, text="Downsize", style="W.TButton", cursor="hand2", command= lambda: root.wm_attributes("-fullscreen", False))
        downsizeBtn.pack(side="right")

        maximizeBtn = ttk.Button(bannerFrame, text="Fullscreen", style="W.TButton", cursor="hand2", command= lambda: root.wm_attributes("-fullscreen", True))
        maximizeBtn.pack(side="right")

        settingsBtn = ttk.Button(bannerFrame, text="Settings", style="W.TButton", cursor="hand2",
                                command= lambda: settings())
        settingsBtn.pack(side="right")

        settingsFrame = tk.Frame(mainFrame, background=self.configDict.get("frameBackground"))
        
        def chooseColor(item):
            colorCode = colorchooser.askcolor(title ="Choose color")
            colorCodes = colorCode[1]
            self.configDict.update({item: colorCodes})
            confighandler.saveConfig(self.configDict)


        self.settingsShow = False
        def settings():
            if self.settingsShow:
                settingsFrame.pack_forget()
                self.settingsShow = False
            else:
                settingsFrame.pack(side="right", anchor="ne")
                self.settingsShow = True
        
        settingsBtnLabel = tk.Label(settingsFrame, text="Button Colors", background=self.configDict.get("frameBackground"), foreground=self.configDict.get("labelForeground"))
        settingsBtnLabel.pack()

        settingsBtnFontColor = ttk.Button(settingsFrame, text="Font Color", style="W.TButton", cursor="hand2", command= lambda: chooseColor("buttonForeground")).pack()
        settingsBtnBgColor = ttk.Button(settingsFrame, text="Button BG", style="W.TButton", cursor="hand2", command= lambda: chooseColor("buttonBackground")).pack()


        settingsLabelsLabel = tk.Label(settingsFrame, text="Label Colors", background=self.configDict.get("frameBackground"), foreground=self.configDict.get("labelForeground"))
        settingsLabelsLabel.pack()

        settingsLabelColor = ttk.Button(settingsFrame, text="FG Color", style="W.TButton", cursor="hand2", command= lambda: chooseColor("labelForeground")).pack()

        settingsBkgLabel = tk.Label(settingsFrame, text="Background Color", background=self.configDict.get("frameBackground"), foreground=self.configDict.get("labelForeground"))
        settingsBkgLabel.pack()

        settingsBgColor = ttk.Button(settingsFrame, text="Frame BG Color", style="W.TButton", cursor="hand2", command= lambda: chooseColor("frameBackground")).pack()

        changeBgImageLabel = tk.Label(settingsFrame, text="BG Image", background=self.configDict.get("frameBackground"), foreground=self.configDict.get("labelForeground"))
        changeBgImageLabel.pack()

        settingsBgImage = ttk.Button(settingsFrame, text="Upload", style="W.TButton", cursor="hand2").pack()

        chatBtn = ttk.Button(bannerFrame, text="Chatticus", style="W.TButton", cursor="hand2",
                                command= lambda: minimizeChat())
        chatBtn.pack(side="right", pady=5)

        #Frame for the bottom of the page to house the timeLabel
        bottomFrame = tk.Frame(mainFrame, background=self.configDict.get("frameBackground"))
        bottomFrame.pack(side="bottom", fill="x")

        timeLabel = tk.Label(bottomFrame, font=('helvetica', 16, "bold italic"), background=self.configDict.get("frameBackground"), foreground=self.configDict.get("labelForeground"))
        timeLabel.pack(side="bottom")

        #Function to run the clock in the timeLabel
        def myTime():
            timeString = strftime('%d %b %y @ %H:%M:%S %p')
            timeLabel.config(text=timeString)
            timeLabel.after(1000, myTime)

        #Frame on the left side of the page to house the Work, General, Play and War buttons
        btnFrame = tk.Frame(mainFrame, background=self.configDict.get("frameBackground"))
        btnFrame.pack(side="left", fill="y")

        ####################Work#########################
        workLabel = ttk.Label(btnFrame, text="Work", background=self.configDict.get("frameBackground"), foreground=self.configDict.get("labelForeground"), font=("American typewriter", 20))
        workLabel.pack(pady=10)

        #Getting the OS login to use for file paths
        user = os.getlogin()

        startVSCodeBtn = ttk.Button(btnFrame, text="VSCode", style="W.TButton", cursor="hand2",
                                    command= lambda: os.startfile(r"C:/users/" + user + "/AppData/Local/Programs/Microsoft VS Code/Code.exe"))
        startVSCodeBtn.pack(pady=2)
        startGithubDesktop = ttk.Button(btnFrame, text="GitHub", style="W.TButton", cursor="hand2",
                                        command= lambda: os.startfile(r"C:/users/" + user + "/AppData/Local/GitHubDesktop/GitHubDesktop.exe"))
        startGithubDesktop.pack(pady=2)
        openCommandPrompt = ttk.Button(btnFrame, text="Command", style="W.TButton", cursor="hand2",
                                        command= lambda: os.startfile(r"C:/users/" + user + "/AppData\Roaming\Microsoft\Windows\Start Menu\Programs\System Tools\Command Prompt.lnk"))
        openCommandPrompt.pack(pady=5)
        openBrowser = ttk.Button(btnFrame, text="Browser", style="W.TButton", cursor="hand2",
                                command= lambda: webbrowser.open_new_tab("www.google.com"))
        openBrowser.pack(pady=2)

        #Finding installed version of Teamviewer
        def findTeamviewer():
            try:
                os.startfile(r"C:\Program Files\TeamViewer\TeamViewer.exe")
            except:
                os.startfile(r"C:\Program Files (x86)\TeamViewer\TeamViewer.exe")

        startTeamviewer = ttk.Button(btnFrame, text="TViewer", style="W.TButton", cursor="hand2",
                                        command= lambda: findTeamviewer())
        startTeamviewer.pack(pady=2)
        startShell = ttk.Button(btnFrame, text="Shell", style="W.TButton", cursor="hand2",
                                command= lambda: os.startfile(r"C:/users/" + user + "/AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Windows PowerShell\Windows PowerShell (x86).lnk"))
        startShell.pack(pady=2)
        startDBBrowser = ttk.Button(btnFrame, text="DB", style="W.TButton", cursor="hand2",
                                command= lambda: os.startfile(r"C:\Program Files\DB Browser for SQLite\DB Browser for SQLite.exe"))
        startDBBrowser.pack(pady=2)

        ########################General#####################
        genLabel = ttk.Label(btnFrame, text="General", background=self.configDict.get("frameBackground"), foreground=self.configDict.get("labelForeground"), font=("American typewriter", 20))
        genLabel.pack(pady=10)
        startDiscordbtn = ttk.Button(btnFrame, text="Discord", style="W.TButton", cursor="hand2",
                                    command= lambda: os.startfile(r"C:/users/" + user + "/AppData/Local/Discord/app-1.0.9006/Discord.exe"))
        startDiscordbtn.pack(pady=2)
        startSpotify = ttk.Button(btnFrame, text="Spotify", style="W.TButton", cursor="hand2",
                                command= lambda: os.startfile(r"C:/users/" + user + "/AppData/Local/Microsoft/WindowsApps/Spotify.exe"))
        startSpotify.pack(pady=2)

        ######################Play######################
        playLabel = ttk.Label(btnFrame, text="Play", background=self.configDict.get("frameBackground"), foreground=self.configDict.get("labelForeground"), font=("American typewriter", 20))
        playLabel.pack(pady=10)
        startBlizzardBtn = ttk.Button(btnFrame, text="Blizz", style="W.TButton", cursor="hand2",
                                    command= lambda: os.startfile(r"C:\Program Files (x86)\Battle.net\Battle.net Launcher.exe"))
        startBlizzardBtn.pack(pady=2)
        startSteam = ttk.Button(btnFrame, text="Steam", style="W.TButton", cursor="hand2",
                                command= lambda: os.startfile(r"C:\Program Files (x86)\Steam\steam.exe"))
        startSteam.pack(pady=2)
        startFTB = ttk.Button(btnFrame, text="FTB", style="W.TButton", cursor="hand2",
                                command= lambda: subprocess.call(args="-launchapp cmogmmciplgmocnhikmphehmeecmpaggknkjlbag", executable="C:\Program Files (x86)\Overwolf\OverwolfLauncher.exe"))
        startFTB.pack(pady=2)

        #######################War####################
        warLabel = ttk.Label(btnFrame, text="War", background=self.configDict.get("frameBackground"), foreground=self.configDict.get("labelForeground"), font=("American typewriter", 20))
        warLabel.pack(pady=10)

        startNord = ttk.Button(btnFrame, text="Nord", style="W.TButton", cursor="hand2", 
                                command= lambda: os.startfile(r"C:\Program Files\NordVPN\NordVPN.exe"))
        startNord.pack(pady=2)

        #Finding installed version of chrome to then use for incognito mode
        def chromeRun():
            try:
                subprocess.Popen(["C:\Program Files\Google\Chrome\Application\chrome.exe", "-incognito", "www.google.com"])
            except:
                subprocess.Popen(["C:\Program Files (x86)\Google\Chrome\Application/chrome.exe", "-incognito", "www.google.com"])
        
        startIncognito = ttk.Button(btnFrame, text="Incog", style="W.TButton", cursor="hand2", 
                                    command= lambda: chromeRun())
        startIncognito.pack(pady=2)
        startPutty = ttk.Button(btnFrame, text="Putty", style="W.TButton", cursor="hand2", 
                                command= lambda: os.startfile(r"putty.exe"))
        startPutty.pack(pady=2)

        #Function for opening the dashboard github page
        def callback(url):
            webbrowser.open_new_tab(url)

        link = tk.Label(btnFrame, text="GitHub", font=('Helveticabold', 16, 'italic'), background=self.configDict.get("frameBackground"), foreground=self.configDict.get("labelForeground"), cursor="hand2")
        link.pack(side="bottom", pady=2)
        link.bind("<Button-1>", lambda e:
        callback("https://github.com/deni336/Dashboard"))

#######################Chatbox#####################

        #Frame on the right side of page for housing the chat box and its associated items
        chatFrame = tk.Frame(mainFrame, background=self.configDict.get("frameBackground"))

        self.chatShow = False
        def minimizeChat():
            if self.chatShow:
                chatFrame.pack_forget()
                self.chatShow = False
            else:
                chatFrame.pack(side="right", fill="y")
                self.chatShow = True

        inputUser1 = StringVar()
        usernameInput = Entry(chatFrame, text=inputUser1, background=self.configDict.get("frameBackground"), foreground=self.configDict.get('buttonForeground'), font=('American typewriter', 12, 'bold'))
        usernameInput.pack(side="top", pady=5)
        if self.configDict.get('user') != "":
            self.chatUser = self.configDict.get('user')
            usernameInput.config(state=DISABLED)
            inputUser1.set(self.chatUser)
        else:
            usernameInput.config(state=NORMAL)
            inputUser1.set('Enter your name')
        
        def enterPressed1(event):
            self.chatUser = usernameInput.get()
            usernameInput.config(state=DISABLED)
            confighandler.setUser(self.chatUser)

        usernameInput.bind("<Return>", enterPressed1)
            
        messageInput = StringVar()

        #Frame inside of chatFrame used to align the text box and scroll bar
        messagesFrame = tk.Frame(chatFrame, background=self.configDict.get("frameBackground"))
        messagesFrame.pack()
        scroll = tk.Scrollbar(messagesFrame, orient="vertical", jump=True)
        scroll.pack(side="right", fill='y', pady=2)
        messages = Text(messagesFrame, background=self.configDict.get("frameBackground"), foreground=self.configDict.get('buttonForeground'), font=('American typewriter', 12, 'bold'), width=45, height=30, yscrollcommand=scroll.set)
        messages.pack(padx=5, pady=2, side="left")
        scroll.configure(command=messages.yview)

        inputField = Entry(chatFrame, text=messageInput, background=self.configDict.get("frameBackground"), foreground=self.configDict.get('buttonForeground'), font=('American typewriter', 12, 'bold'))
        inputField.pack(fill="x", padx=5, pady=2)

        #Function to gather string from the Entry inputField, send message to server, clear Entry and scroll message box to end
        def enterPressed(event):
            inputGet = inputField.get()
            chatclient.socketHandling.sendMessage(inputGet)
            messageInput.set('')
            messages.see("end")
            return "break"

        #Binding enter key to the enterPressed function
        inputField.bind("<Return>", enterPressed)
        
        #Connecting to the server
        # Get-Process -Id (Get-NetTCPConnection -LocalPort 6969).OwningProcess
    
        b = chatclient.socketHandling.serverConnection(user, self.chatUser)
        self.idList.append(b[0])
        if b[1] != '':
            messages.config(state=NORMAL)
            messages.insert(END, b[1])
            messages.config(state=DISABLED)
        
        #Threading the receiving functions
        def messageUpdater():
            try:
                response = chatclient.socketHandling.recMessage()
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

        #Calling clock function
        clockProcess = threading.Thread(target=myTime)
        clockProcess.start()

root = MyApp()

icon = "icon.ico"
root.iconbitmap(icon)
#root.state("zoomed")
root.geometry("1920x1080+0+0")
root.title("Dashboard")
root.resizable(True, True)
root.mainloop()


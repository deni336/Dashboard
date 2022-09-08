from textwrap import fill
import tkinter as tk
from tkinter import *
from tkinter import ttk
import os
from time import strftime
from turtle import back, width
import webbrowser
import subprocess
from PIL import ImageTk, Image
import sys, platform
import chatclient


class MyApp(tk.Tk):
    
    def __init__(self):
        self.chatUser = ''
        tk.Tk.__init__(self)
        
        mainFrame = tk.Frame(self)
        mainFrame.pack(expand="1", fill="both")

        bgImage = ImageTk.PhotoImage(Image.open("Escanor.jpg"))

        bgImageLabel = tk.Label(mainFrame, image=bgImage)
        bgImageLabel.place(x=0, y=0)
        bgImageLabel.image = bgImage

        style = ttk.Style()
        style.theme_use('default')
        style.configure('W.TButton', fill="both", borderwidth="5", relief="ridge", font =
                    ('American typewriter', 12, 'bold'),
                        foreground = 'red', background="black")

        bannerFrame = tk.Frame(mainFrame, background="black")
        bannerFrame.pack(fill="x")

        appLabel = ttk.Label(bannerFrame, text="Deni's Dashboard", background="Black", foreground="Red", font=("American typewriter", 25))
        appLabel.pack(side="left")

        exitBtn = ttk.Button(bannerFrame, text="Exit", style="W.TButton", cursor="hand2",
                            command= lambda: root.destroy())
        exitBtn.pack(side="right")

        minimizeBtn = ttk.Button(bannerFrame, text="Minimize", style="W.TButton", cursor="hand2", command= lambda: root.state("icon"))
        minimizeBtn.pack(side="right")

        bottomFrame = tk.Frame(mainFrame, background="black")
        bottomFrame.pack(side="bottom", fill="x")

        myFont = ('helvetica', 16, "bold italic")

        timeLabel = tk.Label(bottomFrame, font=myFont, background="black", foreground="red")
        timeLabel.pack(side="bottom")

        def myTime():
            timeString = strftime('%d %b %y %H:%M:%S %p')
            timeLabel.config(text=timeString)
            timeLabel.after(1000, myTime)

        btnFrame = tk.Frame(mainFrame, background="Black")
        btnFrame.pack(side="left", fill="y")

        ####################Work#########################
        workLabel = ttk.Label(btnFrame, text="Work", background="Black", foreground="Red", font=("American typewriter", 20))
        workLabel.pack(pady=10)

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
        genLabel = ttk.Label(btnFrame, text="General", background="Black", foreground="Red", font=("American typewriter", 20))
        genLabel.pack(pady=10)
        startDiscordbtn = ttk.Button(btnFrame, text="Discord", style="W.TButton", cursor="hand2",
                                    command= lambda: os.startfile(r"C:/users/" + user + "/AppData/Local/Discord/app-1.0.9006/Discord.exe"))
        startDiscordbtn.pack(pady=2)
        startSpotify = ttk.Button(btnFrame, text="Spotify", style="W.TButton", cursor="hand2",
                                command= lambda: os.startfile(r"C:/users/" + user + "/AppData/Local/Microsoft/WindowsApps/Spotify.exe"))
        startSpotify.pack(pady=2)

        ######################Play######################
        playLabel = ttk.Label(btnFrame, text="Play", background="Black", foreground="Red", font=("American typewriter", 20))
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
        warLabel = ttk.Label(btnFrame, text="War", background="Black", foreground="Red", font=("American typewriter", 20))
        warLabel.pack(pady=10)

        startNord = ttk.Button(btnFrame, text="Nord", style="W.TButton", cursor="hand2", 
                                command= lambda: os.startfile(r"C:\Program Files\NordVPN\NordVPN.exe"))
        startNord.pack(pady=2)

        def chromeRun():
            try:
                subprocess.Popen(["C:\Program Files\Google\Chrome\Application\chrome.exe", "-incognito", "www.google.com"])
            finally:
                subprocess.Popen(["C:\Program Files (x86)\Google\Chrome\Application/chrome.exe", "-incognito", "www.google.com"])
        

        startIncognito = ttk.Button(btnFrame, text="Incog", style="W.TButton", cursor="hand2", 
                                    command= lambda: subprocess.Popen(chromeRun))
        startIncognito.pack(pady=2)
        startPutty = ttk.Button(btnFrame, text="Putty", style="W.TButton", cursor="hand2", 
                                command= lambda: os.startfile(r"putty.exe"))
        startPutty.pack(pady=2)


        def callback(url):
            webbrowser.open_new_tab(url)

        link = tk.Label(btnFrame, text="GitHub", font=('Helveticabold', 16, 'italic'), background="black", fg="red", cursor="hand2")
        link.pack(side="bottom", pady=2)
        link.bind("<Button-1>", lambda e:
        callback("https://github.com/deni336/Dashboard"))

        chatFrame = tk.Frame(mainFrame, background="black")
        chatFrame.pack(side="right", fill="y")
        
        chatLabel = tk.Label(chatFrame, text="Chatticus", background="Black", foreground="red", font=("American typewriter", 20))
        chatLabel.pack(side="top")

        inputUser1 = StringVar()
        inputUser1.set('Enter your name')
        usernameInput = Entry(chatFrame, text=inputUser1, background="black", foreground="red", font=('American typewriter', 12, 'bold'))
        usernameInput.pack(side="top")

        def enterPressed1(event):
            self.chatUser = usernameInput.get()
            usernameInput.config(state=DISABLED)

        usernameInput.bind("<Return>", enterPressed1)

        inputUser = StringVar()
        inputUser.set('Welcome ' + self.chatUser)
        
        messages = Text(chatFrame, background="black", foreground="red", font=('American typewriter', 12, 'bold'))
        messages.pack()

        # def fromServer(fromUser, message):
        #     messages.config(state=NORMAL)
        #     messages.insert(INSERT, '\n' fromUser + ':' + message)
        #     messages.config(state=DISABLED)

        inputField = Entry(chatFrame, text=inputUser, background="black", foreground="red", font=('American typewriter', 12, 'bold'))
        inputField.pack(fill="x")

        def enterPressed(event):
            inputGet = inputField.get()
            print(inputGet)
            messages.config(state=NORMAL)
            messages.insert(INSERT, '\n' + self.chatUser + ':' + inputGet)
            messages.config(state=DISABLED)
            #chatclient.sendMessage(inputGet)
            inputUser.set('')
            # label.pack()
            return "break"
        enterPressed("break")
        inputField.bind("<Return>", enterPressed)
        
    
        myTime()

root = MyApp()

icon = "icon.ico"
root.iconbitmap(icon)
root.wm_attributes('-fullscreen', 'True')
root.state("zoomed")
root.title("Dashboard")

root.mainloop()
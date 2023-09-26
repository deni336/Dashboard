import os, subprocess, webbrowser
from tkinter import *
from tkinter import ttk

from client.config_handler import *
import client.styling_page as styling_page

class ButtonF(Frame):
    configDict = get_config()
    def __init__(self, parent):
        self.user = os.getlogin()
        self.style = styling_page.styler()
        Frame.__init__(self, parent)
        self.parent = parent
        self.configure(background=self.configDict['frameBackground'])
        self.widgets()

    def widgets(self):
        self.pack(side="left", fill="y", anchor='nw')

        self.workLabel = ttk.Label(
            self, 
            text="Work", 
            background=self.configDict["frameBackground"], 
            foreground=self.configDict["labelForeground"], 
            font=("American typewriter", 20)
        ).pack(pady=10)

        self.startVSCodeBtn = ttk.Button(
            self, 
            text="VSCode", 
            style="W.TButton", 
            cursor="hand2",
            command= lambda: os.startfile(r"C:/users/" + self.user + "/AppData/Local/Programs/Microsoft VS Code/Code.exe")
        ).pack(pady=2)

        self.startGithubDesktop = ttk.Button(
            self, 
            text="GitHub", 
            style="W.TButton", 
            cursor="hand2",
            command= lambda: os.startfile(r'C:/users/' + self.user + '/AppData/Local/GitHubDesktop/GitHubDesktop.exe')
        ).pack(pady=2)

        self.openCommandPrompt = ttk.Button(
            self, 
            text="Command", 
            style="W.TButton", 
            cursor="hand2",
            command= lambda: os.startfile(r'C:/users/' + self.user + '/AppData\Roaming\Microsoft\Windows\Start Menu\Programs\System Tools\Command Prompt.lnk')
        ).pack(pady=2)

        self.openBrowser = ttk.Button(
            self, 
            text="Browser", 
            style="W.TButton", 
            cursor="hand2",
            command= lambda: webbrowser.open_new_tab('www.google.com')
        ).pack(pady=2)

        self.startTeamviewer = ttk.Button(
            self, 
            text="TViewer", 
            style="W.TButton", 
            cursor="hand2",
            command= lambda: findTeamviewer()
        ).pack(pady=2)

        self.startShell = ttk.Button(
            self, 
            text="Shell", 
            style="W.TButton", 
            cursor="hand2",
            command= lambda: os.startfile(r'C:/users/' + self.user + '/AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Windows PowerShell\Windows PowerShell (x86).lnk')
        ).pack(pady=2)

        self.startDBBrowser = ttk.Button(
            self, 
            text="DB", 
            style="W.TButton", 
            cursor="hand2",
            command= lambda: os.startfile(r'C:\Program Files\DB Browser for SQLite\DB Browser for SQLite.exe')
        ).pack(pady=2)

        self.genLabel = ttk.Label(
            self, 
            text="General", 
            background=self.configDict["frameBackground"], 
            foreground=self.configDict["labelForeground"], 
            font=("American typewriter", 20)
        ).pack(pady=10)

        self.startDiscordbtn = ttk.Button(
            self, 
            text="Discord", 
            style="W.TButton", 
            cursor="hand2",
            command= lambda: os.startfile(r'C:/users/' + self.user + '/AppData/Local/Discord/app-1.0.9006/Discord.exe')
        ).pack(pady=2)

        self.startSpotify = ttk.Button(
            self, 
            text='Spotify', 
            style='W.TButton', 
            cursor='hand2',
            command= lambda: os.startfile(r'C:/users/' + self.user + '/AppData/Local/Microsoft/WindowsApps/Spotify.exe')
        ).pack(pady=2)

        self.playLabel = ttk.Label(
            self, 
            text="Play", 
            background=self.configDict["frameBackground"], 
            foreground=self.configDict["labelForeground"], 
            font=("American typewriter", 20)
        ).pack(pady=10)

        self.startBlizzardBtn = ttk.Button(
            self, 
            text='Blizz', 
            style='W.TButton', 
            cursor='hand2',
            command= lambda: os.startfile(r'C:\Program Files (x86)\Battle.net\Battle.net Launcher.exe')
        ).pack(pady=2)

        self.startSteam = ttk.Button(
            self, 
            text='Steam', 
            style='W.TButton', 
            cursor='hand2',
            command= lambda: os.startfile(r'C:\Program Files (x86)\Steam\steam.exe')
        ).pack(pady=2)

        self.startFTB = ttk.Button(
            self, 
            text='FTB', 
            style='W.TButton', 
            cursor='hand2',
            command= lambda: subprocess.call(args='-launchapp cmogmmciplgmocnhikmphehmeecmpaggknkjlbag', executable='C:\Program Files (x86)\Overwolf\OverwolfLauncher.exe')
        ).pack(pady=2)

        self.warLabel = ttk.Label(
            self, 
            text="War", 
            background=self.configDict["frameBackground"], 
            foreground=self.configDict["labelForeground"], 
            font=("American typewriter", 20)
        ).pack(pady=10)

        self.startNord = ttk.Button(
            self, 
            text='Nord', 
            style='W.TButton', 
            cursor='hand2', 
            command= lambda: os.startfile(r'C:\Program Files\NordVPN\NordVPN.exe')
        ).pack(pady=2)

        self.startIncognito = ttk.Button(
            self, 
            text='Incog', 
            style='W.TButton', 
            cursor='hand2', 
            command= lambda: chromeRun()
        ).pack(pady=2)

        self.startPutty = ttk.Button(
            self,
            text='Putty',
            style='W.TButton',
            cursor='hand2',
            command= lambda: os.startfile(r'putty.exe')
        ).pack(pady=2)

        self.link = Label(
            self, 
            text="GitHub", 
            font=('Helveticabold', 16, 'italic'), 
            background=self.configDict["frameBackground"], 
            foreground=self.configDict["labelForeground"], 
            cursor="hand2"
        )
        self.link.pack(side="bottom", pady=2)
        self.link.bind(
            "<Button-1>", 
            lambda e: callback("https://github.com/deni336/Dashboard")
        )

        def findTeamviewer():
            try:
                os.startfile(r'C:\Program Files\TeamViewer\TeamViewer.exe')
            except:
                os.startfile(r'C:\Program Files (x86)\TeamViewer\TeamViewer.exe')

        def chromeRun():
            try:
                subprocess.Popen(
                    [
                        'C:\Program Files\Google\Chrome\Application\chrome.exe', 
                        '-incognito', 
                        'www.google.com'
                    ]
                )
            except:
                subprocess.Popen(
                    [
                        'C:\Program Files (x86)\Google\Chrome\Application/chrome.exe', 
                        '-incognito', 
                        'www.google.com'
                    ]
                )
        
        def callback(url):
            webbrowser.open_new_tab(url)
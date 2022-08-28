import tkinter as tk
from tkinter import *
from tkinter import ttk
import os

root = tk.Tk()
root.title("Dashboard")


mainFrame = tk.Frame(root, background="Blue")
mainFrame.grid(columnspan=100, rowspan=100)

appLabel = ttk.Label(mainFrame, text="Deni's Dashboard", background="Blue", foreground="White", font=("Arial", 25))
appLabel.grid(sticky="n", columnspan=3)

####################Work#########################
workLabel = ttk.Label(mainFrame, text="Work", background="Blue", foreground="White", font=("Arial", 18))
workLabel.grid(column=0, row=1, sticky="w")
startVSCodeBtn = ttk.Button(mainFrame, text="VSCode", 
                            command= lambda: os.startfile(r"C:\Users\denis\AppData\Local\Programs\Microsoft VS Code\Code.exe"))
startVSCodeBtn.grid(column=0, row=2, sticky="w")
startGithubDesktop = ttk.Button(mainFrame, text="Ghub Desk",
                                command= lambda: os.startfile(r"C:\Users\denis\Desktop\GitHub Desktop.lnk"))
startGithubDesktop.grid(column=0, row=3, sticky="w")
openCommandPrompt = ttk.Button(mainFrame, text="Command",
                                command= lambda: os.startfile(r"C:\Users\denis\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\System Tools\Command Prompt.lnk"))
openCommandPrompt.grid(column=0, row=4, sticky="w")
openChrome = ttk.Button(mainFrame, text="Chrome",
                        command= lambda: os.startfile(r"C:\Users\Public\Desktop\Google Chrome.lnk"))
openChrome.grid(column=0, row=5, sticky="w")
startShell = ttk.Button(mainFrame, text="Shell",
                        command= lambda: os.startfile(r"C:\Users\denis\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Windows PowerShell\Windows PowerShell (x86).lnk"))
startShell.grid(column=0, row=6, sticky="w")
startDBBrowser = ttk.Button(mainFrame, text="DB",
                        command= lambda: os.startfile(r"C:\Program Files\DB Browser for SQLite\DB Browser for SQLite.exe"))
startDBBrowser.grid(column=0, row=7, sticky="w")

########################General#####################
genLabel = ttk.Label(mainFrame, text="General", background="Blue", foreground="White", font=("Arial", 18))
genLabel.grid(column=1, row=1)
startDiscordbtn = ttk.Button(mainFrame, text="Discord",
                            command= lambda: os.startfile(r"C:\Users\denis\Desktop\Discord.lnk"))
startDiscordbtn.grid(column=1, row=2)
startSpotify = ttk.Button(mainFrame, text="Spotify",
                        command= lambda: os.startfile(r"C:\Users\denis\Desktop\Spotify.lnk"))
startSpotify.grid(column=1, row=3)

######################Play######################
playLabel = ttk.Label(mainFrame, text="Play", background="Blue", foreground="White", font=("Arial", 18))
playLabel.grid(column=2, row=1, sticky="e")
startBlizzardBtn = ttk.Button(mainFrame, text="Blizz",
                            command= lambda: os.startfile(r"C:\Users\Public\Desktop\Battle.net.lnk"))
startBlizzardBtn.grid(column=2, row=2, sticky="e")
startSteam = ttk.Button(mainFrame, text="Steam",
                        command= lambda: os.startfile(r"C:\Users\Public\Desktop\Steam.lnk"))
startSteam.grid(column=2, row=3, sticky="e")
startFTB = ttk.Button(mainFrame, text="FTB",
                        command= lambda: os.startfile(r"C:\Users\denis\Desktop\FTB App.lnk"))
startFTB.grid(column=2, row=4, sticky="e")

icon = r"C:\Users\denis\Documents\icon.ico"
root.geometry('+%d+%d'%(0,0)) 
root.iconbitmap(icon)
#root.overrideredirect(True)
root.attributes("-topmost", True)
root.resizable(0,0)
root.mainloop()
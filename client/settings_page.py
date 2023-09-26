from tkinter import *
from tkinter import ttk, colorchooser, filedialog
from client.config_handler import get_config, save_config, update
import client.styling_page as StylP

class SettingsW(Frame):
    config_dict = get_config()
    settings_bool = False

    def __init__(self, parent, e):
        self.event = e
        Frame.__init__(self, parent)
        self.parent = parent
        self.configure(background=self.config_dict["frameBackground"])
        self.widgets()

    def widgets(self):
        self.settings_btn_label = Label(
            self, 
            text="Button Colors", 
            font=('helvetica', 16, "bold italic"), 
            background=self.config_dict.get('frameBackground'), 
            foreground=self.config_dict.get('labelForeground')
        ).pack()

        self.settings_btn_font_color = ttk.Button(
            self, 
            text="Font Color", 
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: self.choose_color("buttonForeground")
        ).pack()

        self.settings_btn_bg_color = ttk.Button(
            self, 
            text="Button BG", 
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: self.choose_color("buttonBackground")
        ).pack()

        self.settings_labels_label = Label(
            self, 
            text="Label Colors", 
            font=('helvetica', 16, "bold italic"), 
            background=self.config_dict["frameBackground"], 
            foreground=self.config_dict["labelForeground"]
        ).pack()

        self.settings_label_color = ttk.Button(
            self, 
            text="FG Color", 
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: self.choose_color("labelForeground")
        ).pack()

        self.settings_bkg_label = Label(
            self, 
            text="Background Color", 
            font=('helvetica', 16, "bold italic"), 
            background=self.config_dict["frameBackground"], 
            foreground=self.config_dict["labelForeground"]
        ).pack()

        self.settings_bg_color = ttk.Button(
            self, 
            text="Frame BG Color", 
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: self.choose_color("frameBackground")
        ).pack()

        self.change_bg_image_label = Label(
            self, 
            text="BG Image", 
            font=('helvetica', 16, "bold italic"), 
            background=self.config_dict["frameBackground"], 
            foreground=self.config_dict["labelForeground"]
        ).pack()

        self.settings_bg_image = ttk.Button(
            self, 
            text="Upload", 
            style="W.TButton", 
            cursor="hand2",
            command= lambda: self.choose_bg_image()
        ).pack()

        self.work_dir_label = Label(
            self, 
            text="DL Dir", 
            font=('helvetica', 16, "bold italic"), 
            background=self.config_dict["frameBackground"], 
            foreground=self.config_dict["labelForeground"]
        ).pack()

        self.work_dir_btn = ttk.Button(
            self, 
            text="Dir", 
            style="W.TButton", 
            cursor="hand2", 
            command= lambda: self.set_work_dir()
        ).pack()

        # self.bindLabel = Label(
        #     self, 
        #     text="Keybinds", 
        #     font=('helvetica', 16, "bold italic"), 
        #     background=self.configDict["frameBackground"], 
        #     foreground=self.configDict["labelForeground"]
        # ).pack()

        # self.bindBtn = ttk.Button(
        #     self, 
        #     text="Bind", 
        #     style="W.TButton", 
        #     cursor="hand2", 
        #     command= lambda: self.setKeyBinds()
        # ).pack()
    def choose_bg_image(self):
        bg_image_file = filedialog.askopenfilename()
        if bg_image_file == '':
            pass
        else:
            update('bgImage', bg_image_file)
            self.event.update_background(self)

    def set_work_dir(self):
        filename = filedialog.askdirectory()
        if filename == '':
            pass
        else:
            update('workDir', filename)

    def toggle_settings(self):
        if self.settings_bool:
            self.pack_forget()
            self.settings_bool = False
        else:
            self.pack(side="right", anchor="ne")
            self.settings_bool = True

    def choose_color(self, item):
        colorCode = colorchooser.askcolor(title ="Choose color")
        colorCodes = colorCode[1]
        config_dict = get_config()
        config_dict.update({item: colorCodes})
        save_config(config_dict)

from tkinter import Frame, ttk
from client.config_handler import get_config
import client.styling_page as styling_page  # Seems unused, consider removing if it's not used later

class Banner(Frame):
    """Banner class for the GUI application."""
    
    def __init__(self, parent, events):
        """Initializes the banner frame."""
        
        super().__init__(parent)
        self.parent = parent
        
        # Load configuration
        self.config_dict = get_config()
        
        self.event = events
        self.settings_bool = False
        self.chat_bool = False
        self.serv_trans_bool = False

        self.configure(background=self.config_dict['frameBackground'])
        self.create_widgets()

    def create_widgets(self):
        
        ttk.Label(
            self,
            text="Kasugai", 
            background=self.config_dict['frameBackground'],
            foreground=self.config_dict['labelForeground'],
            font=("American typewriter", 25)
        ).pack(side="left")
        
        button_config = [
            ("Exit", self.event.on_shutdown),
            ("Minimize", self.event.minimize),
            ("Downsize", self.event.down_size),
            ("Fullscreen", self.event.fullscreen),
            ("Settings", self.event.on_lock_broken),
            ("Chatticus", self.event.toggle_open),
            ("Server", self.event.toggle_serv_trans)
        ]
        
        for text, command in button_config:
            ttk.Button(
                self,
                text=text,
                style="W.TButton",
                cursor="hand2",
                command=command
            ).pack(side="right", pady=5)

        self.pack(fill="x", side="top")

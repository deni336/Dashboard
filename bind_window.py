from tkinter import Tk, Label, ttk
from client.config_handler import get_config, save_config, update

class BindWindow(Tk):
    """Class for key binding window."""
    
    config_dict = get_config()

    def __init__(self, *args, **kwargs):
        """Initialize the window."""
        
        super().__init__(*args, **kwargs)
        self.configure(background=self.config_dict.get('frameBackground'))
        self.create_widgets()

    def create_widgets(self):
        
        top_label = Label(self, 
                          text="Bind Your Keys", 
                          font=('Helvetica', 16, "bold italic"),
                          background=self.config_dict.get('frameBackground'), 
                          foreground=self.config_dict.get('labelForeground'))
        
        top_label.pack(side="top")

        bind_button = ttk.Button(self, 
                                 text='Bind', 
                                 style="W.TButton", 
                                 cursor="hand2", 
                                 command=lambda: self.create_bind())
        
        bind_button.pack()

    def create_bind(self, key, bind_to):
        """Create a key binding."""
        
        bind_list = [key, bind_to]
        update('keyBinds', bind_list)


if __name__ == '__main__':
    root = BindWindow()
    icon_path = "icon.ico"
    root.iconbitmap(icon_path)
    root.geometry("300x300+500+500")
    root.title("KeyBinds")
    root.resizable(0, 0)
    root.mainloop()

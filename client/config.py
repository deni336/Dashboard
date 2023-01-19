class Config():
    def __init__(self, u, bbc, bfc, bf, bfs, bfa, lf, lfg, fbg, bi, wm, dl, wd, kb, cp):
        self.id = "primary"
        self.user = u
        self.btn_background_color = bbc
        self.btn_foreground_color = bfc
        self.btn_font = bf
        self.btn_font_size = bfs
        self.btn_font_add = bfa
        self.label_font = lf
        self.label_foreground_color = lfg
        self.frame_background_color = fbg
        self.background_image = bi
        self.window_mode = wm
        self.download = dl
        self.working_directory = wd
        self.key_binds = kb
        self.client_ip = cp
        
    #getter
    @property
    def id(self):
        return self.id
    
    #setter
    @id.setter
    def id(self, value):
        self.id = value  
        
    #getter
    @property
    def user(self):
        return self.user
    
    #setter
    @user.setter
    def user(self, value):
        self.user = value  
    
    
     #getter
    @property
    def btn_background_color(self):
        return self.btn_background_color
    
    #setter
    @btn_background_color.setter
    def btn_background_color(self, value):
        self.btn_background_color = value  
        
     #getter
    @property
    def btn_foreground_color(self):
        return self.btn_foreground_color
    
    #setter
    @btn_foreground_color.setter
    def btn_foreground_color(self, value):
        self.btn_foreground_color = value  
        
     #getter
    @property
    def btn_font(self):
        return self.btn_font
    
    #setter
    @btn_font.setter
    def btn_font(self, value):
        self.btn_font = value
        
    #getter
    @property
    def btn_font_size(self):
        return self.btn_font_size
    
    #setter
    @btn_font_size.setter
    def btn_font_size(self, value):
        self.btn_font_size = value  
        
    #getter
    @property
    def btn_font_add(self):
        return self.btn_font_add
    
    #setter
    @btn_font_add.setter
    def btn_font_add(self, value):
        self.btn_font_add = value  
        
    #getter
    @property
    def label_font(self):
        return self.label_font
    
    #setter
    @label_font.setter
    def label_font(self, value):
        self.label_font = value 
        
    #getter
    @property
    def label_foreground_color(self):
        return self.label_foreground_color
    
    #setter
    @label_foreground_color.setter
    def label_foreground_color(self, value):
        self.label_foreground_color = value
        
    #getter
    @property
    def frame_background_color(self):
        return self.frame_background_color
    
    #setter
    @frame_background_color.setter
    def frame_background_color(self, value):
        self.frame_background_color = value   
        
    #getter
    @property
    def background_image(self):
        return self.background_image
    
    #setter
    @background_image.setter
    def background_image(self, value):
        self.background_image = value   
        
    #getter
    @property
    def window_mode(self):
        return self.window_mode
    
    #setter
    @window_mode.setter
    def window_mode(self, value):
        self.window_mode = value   
        
    #getter
    @property
    def download(self):
        return self.download
    
    #setter
    @download.setter
    def download(self, value):
        self.download = value   
        
    #getter
    @property
    def working_directory(self):
        return self.working_directory
    
    #setter
    @working_directory.setter
    def working_directory(self, value):
        self.working_directory = value   
        
    #getter
    @property
    def key_binds(self):
        return self.key_binds
    
    #setter
    @key_binds.setter
    def key_binds(self, value):
        self.key_binds = value   
        
    #getter
    @property
    def client_ip(self):
        return self.client_ip
    
    #setter
    @client_ip.setter
    def client_ip(self, value):
        self.client_ip = value   
        
               

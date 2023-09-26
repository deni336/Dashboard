# from ChatClient import ChatCl
import client.config_handler as config_handler

class FileManager():
    config_dict = config_handler.get_config()
    
    def whats_avail(self):
        self.config_dict = config_handler.get_config()
        self.list_of_avail_files = self.config_dict.get('download')
        return self.list_of_avail_files

    def download():
        pass

    def delete(self, filename):
        self.list_of_avail_files.remove(filename)
        config_handler.update('download', self.list_of_avail_files)


    def stage(self, ip, size, path):
        self.list_of_avail_files.append([ip, size, path])
        config_handler.update('download', self.list_of_avail_files)
        # ChatClient.sendStage(ChatClient[ip, size, path])
    
    


from src.config_handler import ConfigHandler

class FileManager:
    def __init__(self):
        self.config = ConfigHandler()

    def get_available_files(self):
        files = self.config.get('FileTransfer', 'avail')
        return files if isinstance(files, list) else []

    def delete(self, filename):
        files = self.get_available_files()
        if filename in files:
            files.remove(filename)
            self.config.set('FileTransfer', 'avail', str(files))

    def stage(self, ip, size, path):
        files = self.get_available_files()
        files.append([ip, size, path])
        self.config.set('FileTransfer', 'avail', str(files))

    def download(self):
        raise NotImplementedError("Download functionality is not implemented yet.")
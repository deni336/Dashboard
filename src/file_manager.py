import mimetypes
import os
import uuid
from werkzeug.utils import secure_filename
from src.config_handler import ConfigHandler
from src.kasugai_client import KasugaiClient
from src.global_logger import GlobalLogger

class FileManager:
    def __init__(self):
        self.config = ConfigHandler()
        self.logger = GlobalLogger.get_logger("FileManager")
        self.client = KasugaiClient(
            host=self.config.get('WebServer', 'kasaddress'),
            port=self.config.get('WebServer', 'kasport'),
            file_transfer_host=self.config.get('FileTransfer', 'address'),
            file_transfer_port=self.config.getint('FileTransfer', 'port')
        )

    def send_file(self, file_path, sender_id, recipient_id):
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"No such file: {file_path}")

        mime_type, _ = mimetypes.guess_type(file_path)
        try:
            file_id = self.client.upload_file(
                file_path,
                sender_id=sender_id,
                recipient_id=recipient_id,
                mime_type=mime_type or 'application/octet-stream'
            )
            self.logger.info(f"Uploaded file {file_path} as {file_id} for recipient {recipient_id}")
            return file_id
        except Exception as e:
            self.logger.error(f"Error sending file {file_path}: {e}")
            raise

    def get_metadata(self, file_id):
        try:
            return self.client.get_file_metadata(file_id)
        except Exception as e:
            self.logger.error(f"Error reading file metadata for {file_id}: {e}")
            raise

    def download(self, file_id, metadata=None):
        upload_folder = self.config.get('FileTransfer', 'uploadfolder')
        os.makedirs(upload_folder, exist_ok=True)
        try:
            metadata = metadata or self.get_metadata(file_id)
            filename = secure_filename(metadata.name or file_id) or file_id
            destination_path = self._unique_destination(upload_folder, filename)
            destination_path = self.client.download_file(
                file_id,
                destination_path=destination_path,
                metadata=metadata
            )
            self.logger.info(f"Downloaded file {file_id} to {destination_path}")
            return destination_path
        except Exception as e:
            self.logger.error(f"Error downloading file {file_id}: {e}")
            raise

    @staticmethod
    def _unique_destination(destination_dir, filename):
        path = os.path.join(destination_dir, filename)
        if not os.path.exists(path):
            return path

        stem, ext = os.path.splitext(filename)
        return os.path.join(destination_dir, f"{stem}-{uuid.uuid4().hex[:8]}{ext}")

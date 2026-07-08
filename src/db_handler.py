import datetime
import os
import sqlite3
from cryptography.fernet import Fernet
from src.config_handler import ConfigHandler, get_default_config_path
from src.global_logger import GlobalLogger

class ChatHistory:
    """
    Chat history persistence using SQLite with message encryption.
    """
    def __init__(self):
        # Initialize logger
        self.logger = GlobalLogger.get_logger("ChatHistory")
        config = ConfigHandler()

        # Load or generate encryption key
        key = config.get('Database', 'encryption_key')
        if not key:
            key = Fernet.generate_key().decode()
            config.set('Database', 'encryption_key', key)
        self.fernet = Fernet(key.encode())

        # Resolve the SQLite database path
        base_dir = os.path.dirname(get_default_config_path())
        self.db_path = os.path.join(base_dir, config.get('Database', 'dbpath'))
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    message TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            ''')
        self.logger.info(f"Connected to SQLite database at {self.db_path}")

    def add_message(self, name, message, time):
        """
        Encrypt and insert a chat message row.
        """
        encrypted = self.fernet.encrypt(message.encode()).decode()
        try:
            ts = datetime.datetime.fromisoformat(time)
        except Exception:
            ts = datetime.datetime.utcnow()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                'INSERT INTO chat_history (name, message, timestamp) VALUES (?, ?, ?)',
                (name, encrypted, ts.isoformat())
            )
        self.logger.info(f"Inserted message for {name} at {ts.isoformat()}")

    def view_messages(self):
        """
        Retrieve all messages, decrypting content, ordered by timestamp.
        Returns a list of tuples: (id, name, message, timestamp).
        """
        results = []
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                'SELECT id, name, message, timestamp FROM chat_history ORDER BY timestamp ASC'
            ).fetchall()
        for row_id, name, message, timestamp in rows:
            try:
                decrypted = self.fernet.decrypt(message.encode()).decode()
            except Exception as e:
                self.logger.error(f"Decryption error for row {row_id}: {e}")
                continue
            results.append((str(row_id), name, decrypted, timestamp))
        self.logger.info(f"Retrieved {len(results)} messages from SQLite")
        return results

    def erase_history(self):
        """
        Delete all chat history rows.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('DELETE FROM chat_history')
        self.logger.info("Erased all chat history in SQLite")

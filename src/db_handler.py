import sqlite3
from sqlite3 import Error
import os, getpass
from src.global_logger import GlobalLogger
from src.db_utils import get_default_db_path

# Create the table in the database if it doesn't exist
class DatabaseCreation:
    def __init__(self, db_path):
        self.db_path = db_path
        self.logger = GlobalLogger.get_logger('DatabaseCreation')

    def create_table(self):
        """Create the HIST table if it doesn't exist"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                sql = '''
                CREATE TABLE IF NOT EXISTS HIST (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    NAME TEXT NOT NULL,
                    MESSAGE TEXT NOT NULL,
                    TIME TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                '''
                conn.execute(sql)
                self.logger.info("Table 'HIST' is ready.")
        except Error as e:
            self.logger.error(f"Error creating table: {e}")

# Manage adding, viewing, and deleting messages in the database
class ChatHistory:
    def __init__(self, db_path):
        self.db_path = db_path
        self.logger = GlobalLogger.get_logger('ChatHistory')

    def add_message(self, name, message, time):
        """Add a new message to the HIST table"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                sql = '''INSERT INTO HIST (NAME, MESSAGE, TIME) VALUES (?, ?, ?)'''
                conn.execute(sql, (name, message, time))
                self.logger.info(f"Message added: {name} - {message} at {time}")
        except Error as e:
            self.logger.error(f"Error adding message: {e}")

    def view_messages(self):
        """Retrieve all messages from the HIST table"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                sql = '''SELECT * FROM HIST'''
                cur = conn.cursor()
                cur.execute(sql)
                rows = cur.fetchall()
                self.logger.info(f"Fetched {len(rows)} messages from history.")
                return rows
        except Error as e:
            self.logger.error(f"Error retrieving messages: {e}")
            return []

    def erase_history(self):
        """Delete all messages from the HIST table"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                sql = '''DELETE FROM HIST'''
                conn.execute(sql)
                self.logger.info("All chat history has been erased.")
        except Error as e:
            self.logger.error(f"Error erasing chat history: {e}")

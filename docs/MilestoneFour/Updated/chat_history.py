import pymongo
from pymongo import MongoClient, ASCENDING
from datetime import datetime
from cryptography.fernet import Fernet
import os

class ChatHistory:
    def __init__(self, uri=None, db_name='KasugaiDB', collection='ChatHistory'):
        self.uri = uri or "mongodb://localhost:27017"
        self.client = MongoClient(self.uri)
        self.db = self.client[db_name]
        self.collection = self.db[collection]
        self.collection.create_index([("timestamp", ASCENDING)])
        self.key = os.getenv('CHAT_HISTORY_KEY') or Fernet.generate_key()
        self.fernet = Fernet(self.key)

    def add_message(self, name, message, timestamp=None):
        timestamp = timestamp or datetime.utcnow().isoformat()
        encrypted_message = self.fernet.encrypt(message.encode()).decode()
        doc = {"name": name, "message": encrypted_message, "timestamp": timestamp}
        self.collection.insert_one(doc)
        print(f"Message from {name} added.")

    def view_messages(self):
        history = []
        for doc in self.collection.find().sort("timestamp", ASCENDING):
            decrypted_msg = self.fernet.decrypt(doc["message"].encode()).decode()
            history.append((doc["name"], decrypted_msg, doc["timestamp"]))
        return history

    def erase_history(self):
        self.collection.delete_many({})
        print("All chat history erased.")

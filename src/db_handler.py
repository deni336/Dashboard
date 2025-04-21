import datetime
from pymongo import MongoClient
from cryptography.fernet import Fernet
from src.config_handler import ConfigHandler
from src.global_logger import GlobalLogger

class ChatHistory:
    """
    Chat history persistence using MongoDB with message encryption and indexing.
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

        # Connect to MongoDB
        uri = config.get('Database', 'mongo_uri')
        db_name = config.get('Database', 'mongo_db')
        coll_name = config.get('Database', 'mongo_collection')

        self.client = MongoClient(uri)
        self.db = self.client[db_name]
        self.collection = self.db[coll_name]

        # Create an index on timestamp for fast queries
        self.collection.create_index("timestamp")
        self.logger.info(f"Connected to MongoDB at {uri}/{db_name}.{coll_name}")

    def add_message(self, name, message, time):
        """
        Encrypt and insert a chat message document.
        """
        encrypted = self.fernet.encrypt(message.encode()).decode()
        try:
            ts = datetime.datetime.fromisoformat(time)
        except Exception:
            ts = datetime.datetime.utcnow()
        doc = {
            'name': name,
            'message': encrypted,
            'timestamp': ts
        }
        self.collection.insert_one(doc)
        self.logger.info(f"Inserted message for {name} at {ts.isoformat()}")

    def view_messages(self):
        """
        Retrieve all messages, decrypting content, ordered by timestamp.
        Returns a list of tuples: (id, name, message, timestamp).
        """
        results = []
        cursor = self.collection.find().sort('timestamp', 1)
        for doc in cursor:
            try:
                decrypted = self.fernet.decrypt(doc['message'].encode()).decode()
            except Exception as e:
                self.logger.error(f"Decryption error for doc {doc['_id']}: {e}")
                continue
            results.append((str(doc['_id']), doc['name'], decrypted, doc['timestamp'].isoformat()))
        self.logger.info(f"Retrieved {len(results)} messages from MongoDB")
        return results

    def erase_history(self):
        """
        Delete all chat history documents.
        """
        self.collection.delete_many({})
        self.logger.info("Erased all chat history in MongoDB")

import sqlite3
import threading
import os
from datetime import datetime
from server_logger import ServerLogger

class ServerStorage:
   def __init__(self, db_file=None):
      # Initialize logger for ServerStorage
      self.logger = ServerLogger.get_logger("ServerStorage")
      if db_file is None:
            db_file = os.path.join(os.getcwd(), 'kasugai.db')
      self.db_file = db_file
      self._db_lock = threading.Lock()
      self.init_db()

   def get_connection(self):
      """
      Returns a new SQLite connection.
      The connection is created with check_same_thread=False for thread safety.
      """
      return sqlite3.connect(self.db_file, check_same_thread=False)

   def init_db(self):
      """
      Initialize the database by creating Users, Rooms, and Messages tables if they do not exist.
      """
      try:
            with self._db_lock, self.get_connection() as conn:
               cur = conn.cursor()
               cur.execute('''
                  CREATE TABLE IF NOT EXISTS Users (
                        user_id TEXT PRIMARY KEY,
                        name TEXT,
                        status TEXT
                  )
               ''')
               cur.execute('''
                  CREATE TABLE IF NOT EXISTS Rooms (
                        room_id TEXT PRIMARY KEY,
                        name TEXT,
                        participant_ids TEXT,
                        type TEXT,
                        creator_id TEXT,
                        password TEXT
                  )
               ''')
               cur.execute('''
                  CREATE TABLE IF NOT EXISTS Messages (
                        message_id TEXT PRIMARY KEY,
                        room_id TEXT,
                        sender_id TEXT,
                        content TEXT,
                        timestamp TEXT
                  )
               ''')
               conn.commit()
            self.logger.info("Database initialized successfully.")
      except Exception as e:
            self.logger.error(f"Error initializing database: {e}")

   def add_user(self, user_id, name, status):
      """
      Inserts a new user record into the Users table.
      """
      try:
            with self._db_lock, self.get_connection() as conn:
               cur = conn.cursor()
               cur.execute("INSERT INTO Users (user_id, name, status) VALUES (?, ?, ?)",
                           (user_id, name, status))
               conn.commit()
            self.logger.info(f"User {user_id} added successfully.")
      except Exception as e:
            self.logger.error(f"Error adding user {user_id}: {e}")
            raise

   def update_user_status(self, user_id, status):
      """
      Updates the status of an existing user.
      """
      try:
            with self._db_lock, self.get_connection() as conn:
               cur = conn.cursor()
               cur.execute("UPDATE Users SET status = ? WHERE user_id = ?",
                           (status, user_id))
               conn.commit()
            self.logger.info(f"User {user_id} status updated to {status}.")
      except Exception as e:
            self.logger.error(f"Error updating status for user {user_id}: {e}")
            raise

   def get_user(self, user_id):
      """
      Retrieves a user record by user_id.
      Returns a tuple: (user_id, name, status) or None if not found.
      """
      try:
            with self._db_lock, self.get_connection() as conn:
               cur = conn.cursor()
               cur.execute("SELECT user_id, name, status FROM Users WHERE user_id = ?", (user_id,))
               user = cur.fetchone()
               if user:
                  self.logger.info(f"User {user_id} retrieved successfully.")
               else:
                  self.logger.warning(f"User {user_id} not found.")
               return user
      except Exception as e:
            self.logger.error(f"Error retrieving user {user_id}: {e}")
            raise

   def list_users(self):
      """
      Returns a list of all users.
      """
      try:
            with self._db_lock, self.get_connection() as conn:
               cur = conn.cursor()
               cur.execute("SELECT user_id, name, status FROM Users")
               users = cur.fetchall()
            self.logger.info(f"Listed {len(users)} users successfully.")
            return users
      except Exception as e:
            self.logger.error(f"Error listing users: {e}")
            raise

   def add_room(self, room_id, name, participant_ids, room_type, creator_id, password):
      """
      Inserts a new room record.
      participant_ids should be provided as a list of user IDs.
      """
      try:
            with self._db_lock, self.get_connection() as conn:
               cur = conn.cursor()
               participant_ids_str = ','.join(participant_ids)
               cur.execute(
                  "INSERT INTO Rooms (room_id, name, participant_ids, type, creator_id, password) VALUES (?, ?, ?, ?, ?, ?)",
                  (room_id, name, participant_ids_str, room_type, creator_id, password)
               )
               conn.commit()
            self.logger.info(f"Room {room_id} added successfully.")
      except Exception as e:
            self.logger.error(f"Error adding room {room_id}: {e}")
            raise

   def get_room(self, room_id):
      """
      Retrieves a room record by room_id.
      Returns a dictionary with room details or None if not found.
      """
      try:
            with self._db_lock, self.get_connection() as conn:
               cur = conn.cursor()
               cur.execute(
                  "SELECT room_id, name, participant_ids, type, creator_id, password FROM Rooms WHERE room_id = ?",
                  (room_id,)
               )
               row = cur.fetchone()
               if row:
                  participant_ids = row[2].split(',') if row[2] else []
                  self.logger.info(f"Room {room_id} retrieved successfully.")
                  return {
                        'room_id': row[0],
                        'name': row[1],
                        'participant_ids': participant_ids,
                        'type': row[3],
                        'creator_id': row[4],
                        'password': row[5]
                  }
               else:
                  self.logger.warning(f"Room {room_id} not found.")
                  return None
      except Exception as e:
            self.logger.error(f"Error retrieving room {room_id}: {e}")
            raise

   def list_rooms(self):
      """
      Returns a list of all room records.
      """
      try:
            with self._db_lock, self.get_connection() as conn:
               cur = conn.cursor()
               cur.execute("SELECT room_id, name, participant_ids, type, creator_id, password FROM Rooms")
               rows = cur.fetchall()
               rooms_list = []
               for row in rows:
                  participant_ids = row[2].split(',') if row[2] else []
                  rooms_list.append({
                        'room_id': row[0],
                        'name': row[1],
                        'participant_ids': participant_ids,
                        'type': row[3],
                        'creator_id': row[4],
                        'password': row[5]
                  })
            self.logger.info(f"Listed {len(rooms_list)} rooms successfully.")
            return rooms_list
      except Exception as e:
            self.logger.error(f"Error listing rooms: {e}")
            raise

   def add_message(self, message_id, room_id, sender_id, content, timestamp=None):
      """
      Inserts a new message record into the Messages table.
      If no timestamp is provided, the current datetime will be used.
      """
      try:
            if timestamp is None:
               timestamp = datetime.utcnow().isoformat()
            with self._db_lock, self.get_connection() as conn:
               cur = conn.cursor()
               cur.execute(
                  "INSERT INTO Messages (message_id, room_id, sender_id, content, timestamp) VALUES (?, ?, ?, ?, ?)",
                  (message_id, room_id, sender_id, content, timestamp)
               )
               conn.commit()
            self.logger.info(f"Message {message_id} added successfully to room {room_id}.")
      except Exception as e:
            self.logger.error(f"Error adding message {message_id} in room {room_id}: {e}")
            raise

   def get_messages_for_room(self, room_id):
      """
      Retrieves all messages for a given room ordered by timestamp.
      Returns a list of tuples.
      """
      try:
            with self._db_lock, self.get_connection() as conn:
               cur = conn.cursor()
               cur.execute(
                  "SELECT message_id, room_id, sender_id, content, timestamp FROM Messages WHERE room_id = ? ORDER BY timestamp",
                  (room_id,)
               )
               messages = cur.fetchall()
            self.logger.info(f"Retrieved {len(messages)} messages for room {room_id}.")
            return messages
      except Exception as e:
            self.logger.error(f"Error retrieving messages for room {room_id}: {e}")
            raise

   def delete_messages_for_room(self, room_id):
      """
      Deletes all messages for a specific room.
      """
      try:
            with self._db_lock, self.get_connection() as conn:
               cur = conn.cursor()
               cur.execute("DELETE FROM Messages WHERE room_id = ?", (room_id,))
               conn.commit()
            self.logger.info(f"Deleted messages for room {room_id} successfully.")
      except Exception as e:
            self.logger.error(f"Error deleting messages for room {room_id}: {e}")
            raise

if __name__ == '__main__':
   storage = ServerStorage()
   print("Database initialized!")

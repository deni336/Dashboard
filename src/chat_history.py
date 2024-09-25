import sqlite3
from sqlite3 import Error
import os

# Define the path to the chat history database
default_user = os.getlogin()
db = fr"C:/Users/{default_user}/Kasugai/ChatHistory.db"

# Create a connection to the SQLite database
def create_connection(db_file):
    """ Create a database connection to the SQLite database specified by db_file """
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        return conn
    except Error as e:
        print(f"Error: {e}")
    return conn

# Create the table in the database if it doesn't exist
class DatabaseCreation:
    def __init__(self) -> None:
        self.conn = create_connection(db)

    def create_table(self):
        """ Create the HIST table if it doesn't exist """
        if self.conn is not None:
            try:
                sql = '''
                CREATE TABLE IF NOT EXISTS HIST (
                    NAME TEXT NOT NULL,
                    MESSAGE TEXT NOT NULL,
                    TIME TEXT NOT NULL
                )
                '''
                cur = self.conn.cursor()
                cur.execute(sql)
                self.conn.commit()
                print("Table 'HIST' is ready.")
            except Error as e:
                print(f"Error creating table: {e}")
            finally:
                self.conn.close()
        else:
            print("Error! Cannot create the database connection.")

# Manage adding, viewing, and deleting messages in the database
class ChatHistory:
    def __init__(self):
        self.conn = create_connection(db)

    def add_message(self, name, message, time):
        """ Add a new message to the HIST table """
        try:
            sql = '''INSERT INTO HIST (NAME, MESSAGE, TIME) VALUES (?, ?, ?)'''
            cur = self.conn.cursor()
            cur.execute(sql, (name, message, time))
            self.conn.commit()
            print(f"Message added: {name} - {message} at {time}")
        except Error as e:
            print(f"Error adding message: {e}")
        finally:
            self.conn.close()

    def view_messages(self):
        """ View all messages from the HIST table """
        message_history = []
        try:
            sql = '''SELECT * FROM HIST'''
            cur = self.conn.cursor()
            cur.execute(sql)
            rows = cur.fetchall()
            for row in rows:
                message_history.append(row)
            print(f"Fetched {len(rows)} messages from history.")
            return message_history
        except Error as e:
            print(f"Error retrieving messages: {e}")
        finally:
            self.conn.close()

    def erase_history(self):
        """ Delete all messages from the HIST table """
        try:
            sql = '''DELETE FROM HIST'''
            cur = self.conn.cursor()
            cur.execute(sql)
            self.conn.commit()
            print("All chat history has been erased.")
        except Error as e:
            print(f"Error erasing chat history: {e}")
        finally:
            self.conn.close()

# Usage example
if __name__ == "__main__":
    # Create the table if it doesn't exist
    db_creation = DatabaseCreation()
    db_creation.create_table()

    # Insert a message into the chat history
    db_manipulation = ChatHistory()
    db_manipulation.add_message("Alice", "Hello, how are you?", "2024-09-25 10:00:00")

    # View all messages
    messages = db_manipulation.view_messages()
    for message in messages:
        print(message)

    # Erase chat history
    db_manipulation.erase_history()

    # Verify chat history is empty
    messages_after_erase = db_manipulation.view_messages()
    print(f"Messages after erasing history: {messages_after_erase}")

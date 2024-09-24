import sqlite3
from sqlite3 import Error, Cursor
import os

default_user = os.getlogin()
db = r"C:/users/"+ default_user +"/ChatHistory.db"

def create_connection(db_file):
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        return conn
    except Error as e:
        print(e)

class DatabaseCreation():
    def __init__(self, create_table) -> None:
        self.create_table = create_table

    def create_table(self):
        conn = create_connection(db)
        sql = '''
        CREATE TABLE IF NOT EXISTS HIST (
            NAME TEXT NOT NULL
            MESSAGE TEXT NOT NULL
            TIME TEXT NOT NULL)
            '''
        cur = conn.cursor()
        cur.execute(sql)
        conn.commit()
        conn.close()
    
class DatabaseManipulation():
    def add_message(self, message):
        conn = create_connection(db)
        sql = '''INSERT INTO HIST (NAME, MESSAGE, TIME) VALUES (?,?,?)
        '''
        cur = conn.cursor()
        cur.execute(sql)
        conn.commit()
        conn.close()

    def view_messages(self):
        message_history = []
        conn = create_connection(db)
        sql = '''SELECT * FORM HIST'''
        cur = conn.cursor()
        read = cur.execute(sql)
        for i in read:
            message_history.append(i)
        return message_history
        


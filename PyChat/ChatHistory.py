import sqlite3
from sqlite3 import Error, Cursor
import os

defaultUser = os.getlogin()
db = r"C:/users/"+ defaultUser +"/ChatHistory.db"

def createConnection(db_file):
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        return conn
    except Error as e:
        print(e)

class DatabaseCreation():
    def __init__(self, createTable) -> None:
        self.createTable = createTable

    def createTable(self):
        conn = createConnection(db)
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
    def addMessage(self, message):
        conn = createConnection(db)
        sql = '''INSERT INTO HIST (NAME, MESSAGE, TIME) VALUES (?,?,?)
        '''

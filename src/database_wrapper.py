from pydantic import BaseModel
import sqlite3

class DBWrapper():

    def __init__(self):
        conn = sqlite3.connect("database.db")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                password TEXT NOT NULL,
                approved BOOLEAN NOT NULL DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()


    def get_db(self):
        conn = sqlite3.connect("database.db")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def add_user(self, Username, Password):
        conn = self.get_db()
        conn.execute(
            "INSERT INTO users (username, password, approved) VALUES (?, ?, ?)",
            (Username, Password, 0)
        )
        conn.commit()

    def get_user(self, username, Password):
        conn = self.get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)  # Note the comma — this must be a tuple
        )
        user = cursor.fetchone()  # Returns a row or None
        return user
    


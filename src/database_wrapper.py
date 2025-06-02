import sqlite3
from user_class import User
from fastapi import HTTPException
from datetime import datetime
from secret import generate_secret_id

class DBWrapper:
    def __init__(self):
        self.db_path = "database.db"
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            session_id TEXT NOT NULL UNIQUE,
            created_at DATETIME NOT NULL,
            expires_at DATETIME NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

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

    def get_connection(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def add_user(self, username, password):
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO users (username, password, approved) VALUES (?, ?, ?)",
                (username, password, 0)
            )
            conn.commit()

    def get_user(self, username):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            return cursor.fetchone()
        
    async def login(self, request: User):
        user = self.get_user(request._credentials.username)
        sessionid = request._credentials.session_id

        if len(sessionid) != 0:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT s.session_id
                    FROM sessions s
                    JOIN users u ON s.user_id = u.id
                    WHERE s.session_id = ? AND u.username = ? AND s.user_id = u.id
                """, (sessionid, request._credentials.username))
                session_row = cursor.fetchone()
                if session_row:
                    print(session_row)
                    return {"status": "success", "username": user["username"]}

        if user and user["password"] == request._credentials.password and user["approved"]:
            return {"status": "success", "username": user["username"]}
        else:
            raise HTTPException(status_code=401, detail="Invalid credentials")
    
    def get_all_users(self) -> list[User]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users")
            users = cursor.fetchall()
            user_list = []
            for user_row in users:
                user_obj = User(username=user_row["username"], password=user_row["password"])
                user_list.append(user_obj)
            return user_list

    def create_session_id(self, user: User, date: datetime):
        # here we check if a session id exists
        # TODO: need to delete expired session ids
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT session_id, expires_at FROM sessions
            JOIN users ON sessions.user_id = users.id
            WHERE users.username = ? AND expires_at > ?
            ORDER BY expires_at DESC
            LIMIT 1
            """, (user._credentials.username, date))
            existing_session = cursor.fetchone()
            if existing_session:
                return existing_session["session_id"]

        session_id = generate_secret_id()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = ?", (user._credentials.username,))
            user_row = cursor.fetchone()
            if not user_row:
                raise HTTPException(status_code=404, detail="User not found")
            user_id = user_row["id"]
            created_at = date
            expires_at = date + 1  #TODO: refactor to use a real timestamp
            cursor.execute(
                "INSERT INTO sessions (user_id, session_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (user_id, session_id, created_at, expires_at)
            )
            conn.commit()
        return session_id
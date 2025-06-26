from enum import Enum

class ConversationType(Enum):
    Direct = "direct"
    Group  = "group"


USER_TABLE_NAME = "users"
SESSION_TABLE_NAME = "sessions"
CONVERSATION_TABLE_NAME = "conversations"
PARTICIPANTS_TABLE_NAME = "participants"
MESSAGE_TABLE_NAME = "messages"


USER_TABLE = """CREATE TABLE IF NOT EXISTS users(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password TEXT NOT NULL,
                    approved BOOLEAN NOT NULL DEFAULT 0
                );"""

SESSION_TABLE = """CREATE TABLE IF NOT EXISTS sessions(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    session_id TEXT NOT NULL UNIQUE,
                    created_at DATETIME NOT NULL,
                    expires_at DATETIME NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );"""

CONVERSATION_TABLE = """CREATE TABLE IF NOT EXISTS conversations(
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT, -- NULL for 1:1 chats, set for group chats
                        type TEXT NOT NULL CHECK (type IN ('direct', 'group')),
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );"""

PARTICIPANTS_TABLE = """CREATE TABLE IF NOT EXISTS participants(
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        conversation_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        last_read_message_id INTEGER,
                        FOREIGN KEY (conversation_id) REFERENCES conversations(id),
                        FOREIGN KEY (user_id) REFERENCES users(id),
                        UNIQUE(conversation_id, user_id)                      
                    );"""

MESSAGE_TABLE = """CREATE TABLE IF NOT EXISTS messages(
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        conversation_id INTEGER NOT NULL,
                        sender_id INTEGER NOT NULL,
                        content TEXT NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (conversation_id) REFERENCES conversations(id),
                        FOREIGN KEY (sender_id) REFERENCES users(id)                 
                    );"""
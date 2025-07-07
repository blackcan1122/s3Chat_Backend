import aiosqlite
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import List, Optional, AsyncGenerator
import db_consts as dbc
import asyncio
from db_consts import *


from fastapi import HTTPException

from secret import generate_secret_id
from db_objects import User
from eventhandler import EventHandler

class DBWrapper:
    def __init__(self, db_path: str = "database.db"):
        self.db_path = db_path
        self.event_handler = EventHandler()
        self.add_user_event = "AddUserEvent"
        self.remove_user_event = "RemoveUserEvent"

    # -------------------------------------------------
    # initialisation
    # -------------------------------------------------
    async def init_db(self) -> None:
        async with aiosqlite.connect(self.db_path) as conn:
            if conn is None:
                print("DB not Found")

            await conn.execute("PRAGMA foreign_keys = ON;")
            await conn.executescript(
                "\n".join([
                    dbc.USER_TABLE,
                    dbc.SESSION_TABLE,
                    dbc.CONVERSATION_TABLE,
                    dbc.PARTICIPANTS_TABLE,
                    dbc.MESSAGE_TABLE
                ])
            )
            await conn.commit()

    # -------------------------------------------------
    # Connection helper
    # -------------------------------------------------
    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        async with aiosqlite.connect(self.db_path) as conn:
            # Enable foreign keys for this connection
            await conn.execute("PRAGMA foreign_keys = ON;")

            # Set row factory
            conn.row_factory = aiosqlite.Row

            # Commit to ensure pragma takes effect
            await conn.commit()

            yield conn


    # -------------------------------------------------
    # User helpers
    # -------------------------------------------------
    async def add_user(self, username: str, password: str, approved: bool = False) -> None:
        async with self.get_connection() as conn:
            try:
                await conn.execute(
                    "INSERT INTO users (username, password, approved) VALUES (?, ?, ?)",
                    (username, password, int(approved)),
                )
                await conn.commit()
                payload = {"adding": username}
            except aiosqlite.IntegrityError:
                raise HTTPException(status_code=409, detail="Username already exists")
            
            await self.event_handler.call_event(self.add_user_event, payload)

            
    async def approve_user(self, username: str) -> None:
        async with self.get_connection() as conn:
            await conn.execute(
                "UPDATE users SET approved = 1 WHERE username = ?",
                (username,),
            )
            await conn.commit()
            payload = {"approve": username}

        await self.event_handler.call_event(self.add_user_event, payload)

    async def reject_user(self, username: str) -> None:
        async with self.get_connection() as conn:
            await conn.execute(
                "UPDATE users SET approved = 0 WHERE username = ?",
                (username,),
            )
            await conn.commit()

        payload = {"reject": username}
        asyncio.create_task(self.event_handler.call_event(self.add_user_event, payload))

    async def get_user(self, username: str) -> Optional[aiosqlite.Row]:
        async with self.get_connection() as conn:
            async with conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ) as cursor:
                return await cursor.fetchone()

    async def get_user_by_id(self, user_id: int) -> Optional[aiosqlite.Row]:
        async with self.get_connection() as conn:
            async with conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cursor:
                return await cursor.fetchone()
            
    async def get_participant_by_user_and_convo(self, user : User, conversation_id : int):
        async with self.get_connection() as conn:
            async with conn.execute(
                f"""
                SELECT *
                FROM {PARTICIPANTS_TABLE_NAME}
                WHERE user_id = (SELECT id FROM users WHERE username = ?)
                  AND conversation_id = ?
                """,
                (user._credentials.username, conversation_id)
            ) as cursor:
                return await cursor.fetchone()
            
    async def get_newest_message_in_conversation(self, conversation_id):
        async with self.get_connection() as conn:
            async with conn.execute(
                f"""
                SELECT *
                FROM {MESSAGE_TABLE_NAME}
                WHERE conversation_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (conversation_id,)
            ) as cursor:
                return await cursor.fetchone()

    async def get_all_users(self) -> List[User]:
        async with self.get_connection() as conn:
            async with conn.execute("SELECT username, password, approved FROM users") as cursor:
                rows = await cursor.fetchall()
        return [User(username=row["username"], password=row["password"], approved=row["approved"]) for row in rows]

    # -------------------------------------------------
    # Session helpers
    # -------------------------------------------------
    async def get_session(self, session_id: str) -> Optional[aiosqlite.Row]:
        async with self.get_connection() as conn:
            async with conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)) as cursor:
                return await cursor.fetchone()

    async def create_session_id(self, user: User, now: Optional[datetime] = None) -> str:
        if not isinstance(now, datetime):
            now = datetime.now(timezone.utc)

        # Try to re‑use a still‑valid session
        async with self.get_connection() as conn:
            async with conn.execute(
                """SELECT session_id, expires_at
                       FROM sessions s
                       JOIN users u ON s.user_id = u.id
                       WHERE u.username = ? AND s.expires_at > ?
                       ORDER BY s.expires_at DESC
                       LIMIT 1""",
                (user._credentials.username, now),
            ) as cursor:
                existing = await cursor.fetchone()
                if existing:
                    return existing["session_id"]

        # Otherwise create a new one
        session_id = generate_secret_id()
        expires_at = now + timedelta(days=1)

        async with self.get_connection() as conn:
            async with conn.execute(
                "SELECT id FROM users WHERE username = ?", (user._credentials.username,)
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="User not found")
            user_id = row["id"]

            await conn.execute(
                "INSERT INTO sessions (user_id, session_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (user_id, session_id, now, expires_at),
            )
            await conn.commit()
        return session_id

    # -------------------------------------------------
    # Authentication / login
    # -------------------------------------------------
    async def login(self, request: User):
        """Validate a login attempt.

        Two allowed flows:
        1. *Session flow*: client sends **both** ``username`` and ``session_id``;
           we accept only if the session exists, is not expired, *and* belongs
           to that exact username.
        2. *Password flow*: client sends ``username`` and ``password``;
           we accept if the user is approved and the password matches.
        """
        now = datetime.now(timezone.utc)
        creds = request._credentials
        # ---------------------------
        # 1. Session‑based login
        # ---------------------------
        if creds.session_id:
            print(f"Session Based Login: {creds.username}")
            # A username *must* accompany a session‑id in this flow.
            if not creds.username:
                raise HTTPException(status_code=400, detail="Username is required when using session_id")

            session_row = await self.get_session(creds.session_id)
            if session_row:
                expires = session_row["expires_at"]

                # --- Option B: coerce only here ----------------------------------
                if isinstance(expires, str):                 # comes back as TEXT
                    try:
                        expires = datetime.fromisoformat(expires)
                    except ValueError:
                        # Fallback for the default SQLite “YYYY-MM-DD HH:MM:SS”
                        expires = datetime.strptime(expires, "%Y-%m-%d %H:%M:%S")
                    if expires.tzinfo is None:               # make it comparable to `now`
                        expires = expires.replace(tzinfo=timezone.utc)
                # ----------------------------------------------------------------

                if expires > now:
                    user_row = await self.get_user_by_id(session_row["user_id"])
                if not user_row or user_row["username"] != creds.username:
                    raise HTTPException(status_code=401, detail="Session does not belong to this user")
                if user_row["approved"]:
                    return {"status": "success", "username": user_row["username"]}
                raise HTTPException(status_code=401, detail="User not approved")
            # fall‑through to password flow if session missing/expired

        # ---------------------------
        # 2. Username / password flow
        # ---------------------------
        print(f"Password Based Login: {creds.username}")
        user_row = await self.get_user(creds.username)
        if (
            user_row
            and user_row["password"] == creds.password
            and user_row["approved"]
        ):
            return {"status": "success", "username": user_row["username"]}

        # If we reach this point, authentication failed
        raise HTTPException(status_code=401, detail="Invalid credentials")
    

    """
    a message object from the frontend would look something like this:
    message_data = {
        "type": "message",
        "data": {
            "msg": "Hello, how are you?"
        },
        "from": "alice",           # sender's username
        "to": "bob",               # recipient's username or group id
        "chat_type": "direct"      # or "group"
    }
    
    """
    async def add_message(self, message, sender_user : User):
        str_msg = message["data"]["msg"]
        convo_id = message["to"]  # conversation_id (int)

        # Get sender's user_id
        async with self.get_connection() as conn:
            await conn.execute(
                f"INSERT INTO {dbc.MESSAGE_TABLE_NAME} (conversation_id, sender_id, content, created_at) VALUES (?, ?, ?, ?)",
                (convo_id, await sender_user.set_id(), str_msg, datetime.now()),
            )
            await conn.commit()

    async def get_participants_from_convo(self, conversation_id):
        async with self.get_connection() as conn:
            async with conn.execute(
                f"""
                SELECT p.id as participant_id, u.id as user_id, u.username
                FROM {PARTICIPANTS_TABLE_NAME} p
                JOIN users u ON p.user_id = u.id
                WHERE p.conversation_id = ?
                """,
                (conversation_id,)
            ) as cursor:
                rows = await cursor.fetchall()
            return [
                {
                    "participant_id": row["participant_id"],
                    "user_id": row["user_id"],
                    "username": row["username"]
                }
                for row in rows
            ]
        
    async def find_unread_messages(self, user: User):
        await user.set_id(self)

        async with self.get_connection() as conn:
            # Get all participant entries for this user
            async with conn.execute(
                f"""
                SELECT p.id as participant_id, p.conversation_id, p.last_read_message_id
                FROM {PARTICIPANTS_TABLE_NAME} p
                JOIN users u ON p.user_id = u.id
                WHERE u.username = ?
                """,
                (user._credentials.username,)
            ) as cursor:
                participant_rows = await cursor.fetchall()

            unread_conversations = []

            for row in participant_rows:
                conversation_id = row["conversation_id"]
                last_read_message_id = row["last_read_message_id"]

                # Count unread messages from others
                async with conn.execute(
                    f"""
                    SELECT COUNT(*) as unread_count
                    FROM {MESSAGE_TABLE_NAME}
                    WHERE conversation_id = ?
                      AND id > COALESCE(?, 0)
                      AND sender_id != ?
                    """,
                    (conversation_id, last_read_message_id, user._id)
                ) as msg_cursor:
                    msg_row = await msg_cursor.fetchone()
                    unread_count = msg_row["unread_count"] if msg_row else 0

                if unread_count > 0:
                    # Get conversation type and name
                    async with conn.execute(
                        f"""
                        SELECT type, name
                        FROM {CONVERSATION_TABLE_NAME}
                        WHERE id = ?
                        """,
                        (conversation_id,)
                    ) as convo_cursor:
                        convo_row = await convo_cursor.fetchone()
                    if convo_row is None:
                        continue

                    convo_type = convo_row["type"]
                    if convo_type == ConversationType.Direct.value:
                        # Find the other participant's username
                        async with conn.execute(
                            f"""
                            SELECT u.username
                            FROM {PARTICIPANTS_TABLE_NAME} p
                            JOIN users u ON p.user_id = u.id
                            WHERE p.conversation_id = ? AND u.username != ?
                            LIMIT 1
                            """,
                            (conversation_id, user._credentials.username)
                        ) as other_cursor:
                            other_row = await other_cursor.fetchone()
                        display_name = other_row["username"] if other_row else None
                    elif convo_type == ConversationType.Group.value:
                        display_name = convo_row["name"]
                    else:
                        display_name = None

                    unread_conversations.append({
                        **row,
                        "display_name": display_name,
                        "type": convo_type,
                        "unread_count": unread_count
                    })

            return [conv["display_name"] for conv in unread_conversations if conv["display_name"]]


    async def get_messages_from(self, conversation_id: int, last_message: Optional[int] = None) -> list[dict]:
        limit = 10
        async with self.get_connection() as conn:
            if last_message is None:
                async with conn.execute(
                    f'''
                    SELECT m.id, m.content, m.created_at
                    FROM {MESSAGE_TABLE_NAME} m
                    WHERE m.conversation_id = ?
                    ORDER BY m.id DESC
                    LIMIT ?
                    ''',
                    (conversation_id, limit)
                ) as cursor:
                    rows = await cursor.fetchall()
            else:
                async with conn.execute(
                    f'''
                    SELECT id FROM {MESSAGE_TABLE_NAME}
                    WHERE conversation_id = ? AND content = ?
                    ORDER BY id DESC
                    LIMIT 1
                    ''',
                    (conversation_id, last_message)
                ) as id_cursor:
                    id_row = await id_cursor.fetchone()
                if not id_row:
                    rows = []
                else:
                    message_id = id_row["id"]
                    # Get 10 messages older than the found message id
                    async with conn.execute(
                        f'''
                        SELECT m.id, m.content
                        FROM {MESSAGE_TABLE_NAME} m
                        WHERE m.conversation_id = ? AND m.id < ?
                        ORDER BY m.id DESC
                        LIMIT ?
                        ''',
                        (conversation_id, message_id, limit)
                    ) as cursor:
                        rows = await cursor.fetchall()

        return [
            {"id": row["id"], "content": row["content"]}
            for row in reversed(rows)
        ]
    
    async def get_user_groups(self, username: str) -> list[dict]:
        async with self.get_connection() as conn:
            async with conn.execute(
                f"""
                SELECT c.*
                FROM {CONVERSATION_TABLE_NAME} c
                JOIN {PARTICIPANTS_TABLE_NAME} p ON c.id = p.conversation_id
                JOIN {USER_TABLE_NAME} u ON p.user_id = u.id
                WHERE u.username = ? AND c.type = ?
                """,
                (username, ConversationType.Group.value)
            ) as cursor:
                rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def create_conversation(self, name: str | None, type: ConversationType, creator: int) -> bool:
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                f"INSERT INTO {CONVERSATION_TABLE_NAME} (name, type, creator) VALUES (?, ?, ?)",
                (name, type.value, creator),
            )
            await conn.commit()
            if cursor.rowcount > 0:
                conversation_id = cursor.lastrowid
                await self.create_participants(conversation_id, creator)
                return True
                

    async def remove_participant(self, group_id, user_id):
        async with self.get_connection() as conn:
            await conn.execute(
                f"DELETE FROM {PARTICIPANTS_TABLE_NAME} WHERE conversation_id = ? AND user_id = ?",
                (group_id, user_id),
            )
            await conn.commit()

    async def create_participants(self, conversation_id, user_id):
        async with self.get_connection() as conn:
            await conn.execute(
                f"INSERT INTO {PARTICIPANTS_TABLE_NAME} (conversation_id, user_id) VALUES (?, ?)",
                (conversation_id, user_id),
            )
            await conn.commit()

    async def add_message_to_history(self, msg_body, sender : User):
        if msg_body["room_id"] is not None:

            async with self.get_connection() as conn:
                import json
                await conn.execute(
                    f"INSERT INTO {MESSAGE_TABLE_NAME} (conversation_id, sender_id, content, created_at) VALUES (?, ?, ?, ?)",
                    (
                        msg_body["room_id"],
                        await sender.set_id(self),
                        json.dumps(msg_body),
                        msg_body.get("created_at", datetime.now(timezone.utc)),
                    ),
                )
                await conn.commit()
            return
        return

    async def retrieve_direct_convo(self, friend: User, user: User):
        async with self.get_connection() as conn:
            async with conn.execute(
                f"""
                SELECT c.*
                FROM {CONVERSATION_TABLE_NAME} c
                JOIN {PARTICIPANTS_TABLE_NAME} p1 ON c.id = p1.conversation_id
                JOIN {PARTICIPANTS_TABLE_NAME} p2 ON c.id = p2.conversation_id
                WHERE p1.user_id = (SELECT id FROM users WHERE username = ?)
                  AND p2.user_id = (SELECT id FROM users WHERE username = ?)
                  AND c.type = ?
                """,
                (user._credentials.username, friend._credentials.username, ConversationType.Direct.value)
            ) as cursor:
                row = await cursor.fetchone()
                if row == None:
                    return None
                return row["id"]
    
    async def update_last_message(self, participant_id, message_id):
        async with self.get_connection() as conn:
            await conn.execute(
                f"UPDATE {PARTICIPANTS_TABLE_NAME} SET last_read_message_id = ? WHERE id = ?",
                (message_id, participant_id),
            )
            await conn.commit()

    async def create_direct_chat(self, user_a: User, user_b: User):
        """
        Create a direct conversation between user_a and user_b, and add both as participants.
        Returns the conversation id.
        """
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                f"INSERT INTO {CONVERSATION_TABLE_NAME} (name, type) VALUES (?, ?)",
                (None, ConversationType.Direct.value),
            )
            conversation_id = cursor.lastrowid

            # Get user ids
            async with conn.execute("SELECT id FROM users WHERE username = ?", (user_a._credentials.username,)) as cur_a:
                row_a = await cur_a.fetchone()
            async with conn.execute("SELECT id FROM users WHERE username = ?", (user_b._credentials.username,)) as cur_b:
                row_b = await cur_b.fetchone()
            if not row_a or not row_b:
                raise HTTPException(status_code=404, detail="One or both users not found")
            user_a_id = row_a["id"]
            user_b_id = row_b["id"]

            # Add both users as participants
            await conn.execute(
                f"INSERT INTO {PARTICIPANTS_TABLE_NAME} (conversation_id, user_id) VALUES (?, ?)",
                (conversation_id, user_a_id),
            )
            await conn.execute(
                f"INSERT INTO {PARTICIPANTS_TABLE_NAME} (conversation_id, user_id) VALUES (?, ?)",
                (conversation_id, user_b_id),
            )
            await conn.commit()
        return conversation_id



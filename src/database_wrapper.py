import aiosqlite
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import HTTPException

from secret import generate_secret_id
from user_class import User


class DBWrapper:
    """Asynchronous SQLite wrapper suitable for FastAPI / WebSocket workloads.

    Call ``await init_db()`` once during application startup to create tables.
    """

    def __init__(self, db_path: str = "database.db"):
        self.db_path = db_path

    # -------------------------------------------------
    # initialisation
    # -------------------------------------------------
    async def init_db(self) -> None:
        async with aiosqlite.connect(self.db_path) as conn:
            if conn is None:
                print("DB not Found")
            await conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password TEXT NOT NULL,
                    approved BOOLEAN NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS sessions(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    session_id TEXT NOT NULL UNIQUE,
                    created_at DATETIME NOT NULL,
                    expires_at DATETIME NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );
                """
            )
            await conn.commit()

    # -------------------------------------------------
    # Connection helper
    # -------------------------------------------------
    @asynccontextmanager
    async def get_connection(self):
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
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
            except aiosqlite.IntegrityError:
                raise HTTPException(status_code=409, detail="Username already exists")

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

    async def get_all_users(self) -> List[User]:
        async with self.get_connection() as conn:
            async with conn.execute("SELECT username, password FROM users") as cursor:
                rows = await cursor.fetchall()
        return [User(username=row["username"], password=row["password"]) for row in rows]

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

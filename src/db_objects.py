from pydantic import BaseModel
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, APIRouter, status, Depends
import db_consts as dbc
from fastapi import WebSocket
from typing import Optional, List
import datetime

class Credentials(BaseModel):
    username: str
    password: str
    session_id: str
    approved : bool

class User():
    def __init__(self, username: str, password: str, session_id : str = "", approved : bool = False):
        self._credentials = Credentials(username=username, password=password, session_id = session_id, approved=approved)
        self._id = None
        self._isConnected = False
        self._active_connection: Optional[WebSocket] = None

    def set_credentials(self, cred: Credentials):
        self._credentials = Credentials(**cred.model_dump())

    async def set_id(self, db_wrapper):
        async def get_row():
            from database_wrapper import DBWrapper
            row = await db_wrapper.get_user(self._credentials.username)
            if row:
                return row["id"]
            else:
                raise ValueError(f"User '{self._credentials.username}' not found in the database.")
        try:
            self._id = await get_row()
            return self._id
        except ValueError as e:
            print(e)
            return None


class Conversation():
    def __init__(self):
        self._id: Optional[int] = None
        self._name: Optional[str] = None
        self._type: Optional[dbc.ConversationType] = None
        self._created_at: Optional[datetime.datetime] = None
        self._associated_users: Optional[List[Participant]] = None

class Participant():
    def __init__(self):
        self._id: Optional[int] = None
        self._associated_conversation: Optional[Conversation] = None
        self._user: Optional[User] = None
        self._joined_at: Optional[datetime.datetime] = None
        self._last_read_msg: Optional[datetime.datetime] = None



    
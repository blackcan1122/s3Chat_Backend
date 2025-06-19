from pydantic import BaseModel
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, APIRouter, status, Depends

class Credentials(BaseModel):
    username: str
    password: str
    session_id: str
    approved : bool

class User():
    def __init__(self, username: str, password: str, session_id : str = "", approved : bool = False):
        self._credentials = Credentials(username=username, password=password, session_id = session_id, approved=approved)
        self._isConnected = False

    def set_credentials(self, cred: Credentials):
        self._credentials = Credentials(**cred.model_dump())

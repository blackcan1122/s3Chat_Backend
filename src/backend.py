import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, APIRouter, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
import logging
from database_wrapper import DBWrapper
from db_objects import User
from datetime import datetime
import json
from envwrap import EnvParam
from pathlib import Path
import asyncio
from pydantic import BaseModel
from typing import Optional

class UserCreate(BaseModel):
    username: str
    password: str

class ApproveUserRequest(BaseModel):
    username: str

class GetOldMsgRequest(BaseModel):
    oldest_message: Optional[str] = None


class Backend():

    def __init__(self, app : FastAPI, env_params : EnvParam, is_dedicated : bool = False):
        self._env = env_params
        self._app = app
        self._db = DBWrapper(db_path=self._env.ALL_PATHS.db_file)
        self._db.event_handler.add_listener(self._db.add_user_event, self.update_user_array)
        self._active_connections: dict[str,WebSocket] = {}
        self._active_users: dict[str, User] = dict()
        self._users_to_disconnect: list[User] = []
        
        router = APIRouter()

        @router.websocket("/ws/chat")
        async def chat(ws: WebSocket):
            try:
                await ws.accept()
                auth_data = await ws.receive_json()
            except RuntimeError as e:
                print(e)
                return

            username   = auth_data.get("username", "")
            password   = auth_data.get("password", "")
            session_id = auth_data.get("session_id", "")

            incoming_user = User(username, password, session_id)

            try:
                result = await self._db.login(incoming_user)
            except HTTPException:
                await ws.send_json({"type": "response",
                                    "session_id": "0",
                                    "state": "AUTH_FAILED"})
                logging.error(f"Client: {ws.client} not authenticated\nUsername: {username}\nPassword:{password}")
                await ws.close()
                return

            current_user = self._active_users[auth_data["username"]]
            self._active_connections[username] = ws
            current_user._isConnected = True
            sessionid = await self._db.create_session_id(current_user, datetime.now())
            is_admin = False
            if current_user._credentials.username == "Blackcan":
                is_admin = True

            payload = {
                "type": "response",
                "session_id": sessionid,
                "state": "AUTH_SUCCESS",
                "role": is_admin
            }

            await ws.send_text(json.dumps(payload))
            logging.info(f"Client {ws.client} authenticated as {current_user._credentials.username}")
            a : list[User] = await self.retrieve_active_users()
            for i in a:
                print(f"{i._credentials.username} is Online")

            while True:
                if len(self._users_to_disconnect) > 0:
                    for u in self._users_to_disconnect:
                        if u._credentials.username in self._active_connections:
                            print(f"Disconnecting {u._credentials.username}")
                            await self._active_connections[u._credentials.username].close()
                            self._active_connections.pop(u._credentials.username, None)
                            u._isConnected = False
                    self._users_to_disconnect.clear()
                    
                try:
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
                    msg = await ws.receive_text()
                    backend_payload = {
                                "type": "message",
                                "data": msg,
                                "username": current_user._credentials.username
                            }
                    await self._db.add_message(backend_payload)
                    for u, conn in list(self._active_connections.items()):
                        try:
                            payload = {
                                "type": "message",
                                "data": msg,
                                "username": current_user._credentials.username
                            }
                            await conn.send_text(json.dumps(payload))
                        except (WebSocketDisconnect, RuntimeError):
                            self._active_connections.pop(u, None)
                            current_user._isConnected = False
                            print(f"User: {current_user._credentials.username} left")
                            return
                except (WebSocketDisconnect, RuntimeError):
                    for u, conn in list(self._active_connections.items()):
                        if conn == ws:
                            self._active_connections.pop(u, None)
                            current_user._isConnected = False
                            print(f"User: {current_user._credentials.username} left")
                            return

        @router.get("/", include_in_schema=False)
        async def serve_index():
            return FileResponse(str(self._env.ALL_PATHS.build / "index.html"))
          
        @router.get("/api/users")
        async def get_users():
            return [
                {
                    "username": username,
                    "is_online": user._isConnected
                }
                for username, user in self._active_users.items() if user._credentials.approved
            ]
        
        @router.get("/api/all_users")
        async def get_all_users(credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())):
            token = credentials.credentials

            if token != self._env.BEARER_TOKEN:
                raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
            return [
            {
                "username": username,
                "is_online": user._isConnected,
                "is_approved":user._credentials.approved
            }
            for username, user in self._active_users.items()
            ]
        
        @router.post("/add_user", status_code=status.HTTP_201_CREATED)
        async def handle_add_user_request(User : UserCreate):
            print("we Start getting a new user")
            if User.username in self._active_users:
                raise HTTPException(status_code=409, detail="UserName is Taken")
            try:
                await self._db.add_user(User.username, User.password)
            except HTTPException as e:
                raise e


        @router.post("/api/approve_user")
        async def approve_user(
            request: ApproveUserRequest,
            credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())
        ):
            token = credentials.credentials

            if token != self._env.BEARER_TOKEN:
                raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
            await self._db.approve_user(request.username)
            return {"detail": "User approved successfully"}
        

        @router.post("/api/reject_user")
        async def reject_user(
            request: ApproveUserRequest,
            credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())
        ):
            token = credentials.credentials

            if token != self._env.BEARER_TOKEN:
                raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
            await self._db.reject_user(request.username)
            return {"detail": "User rejected successfully"}
        

        @router.post("/api/force_logout")
        async def force_logout(
            request: ApproveUserRequest,
            credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())
        ):
            token = credentials.credentials

            if token != self._env.BEARER_TOKEN:
                raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

            payload = {"logout": request.username}
            await self._db.event_handler.call_event(self._db.add_user_event, payload)
            return {"detail": "User logged out successfully"}
        
        @router.get("/login")
        async def serve_login():
            return FileResponse(str(self._env.ALL_PATHS.build / "index.html"))

        @router.get("/chat")
        async def serve_chat():
            return FileResponse(str(self._env.ALL_PATHS.build / "index.html"))
            
        @router.post("/api/get_old_msg")
        async def get_old_msg(request: GetOldMsgRequest):
            if request.oldest_message:
                full_str = str(request.oldest_message)
                raw_str = str()
                if ':' in full_str:
                    raw_str = full_str.split(':', 1)[1].lstrip()
                else:
                    raw_str = full_str
                messages = await self._db.get_messages_from(raw_str)
                return messages
            else:
                messages = await self._db.get_messages_from(None)
                return messages
            
        # catch other urls
        @router.get("/{full_path:path}", include_in_schema=False)
        async def serve_catch_all(full_path: str):
            return FileResponse(str(self._env.ALL_PATHS.build / full_path))

        if is_dedicated:
            self._app.mount(
                "/static",
                StaticFiles(directory=self._env.ALL_PATHS.static, html=True),
                name="/static",
            )

        self._app.include_router(router)
        self._app.add_event_handler("startup", self.create_tables_at_startup)
        

    async def create_tables_at_startup(self):

        print("Starting DB Init")
        await self._db.init_db()
        users = await self._db.get_all_users()
        self._active_users = {u._credentials.username: u for u in users}

    async def retrieve_active_users(self) -> list[User]:
        iterable_user = self._active_users
        online_users = []
        for u in iterable_user:
            if iterable_user[u]._isConnected:
                online_users.append(iterable_user[u])
        return online_users
    
    async def update_user_array(self, _, payload):
        users = await self._db.get_all_users()
        if not hasattr(self, "_user_lock"):
            self._user_lock = asyncio.Lock()
        async with self._user_lock:
            for u in users:
                if payload is not None and payload.get("reject") == u._credentials.username:
                    print(f"Removing {u._credentials.username} from active users")
                    self._active_users[u._credentials.username] = u
                    self._active_users[u._credentials.username]._credentials.approved = False
                    if u._credentials.username in self._active_connections:
                        payload = {
                            "type": "cmd",
                            "data": "rejected"
                        }
                        print(f"Sending Logout Command to {u._credentials.username}")
                        await self._active_connections[u._credentials.username].send_text(json.dumps(payload))
                    return
                
                if payload is not None and payload.get("approve") == u._credentials.username:
                    print(f"Removing {u._credentials.username} from active users")
                    self._active_users[u._credentials.username] = u
                    self._active_users[u._credentials.username]._credentials.approved = True
                    return

                if payload is not None and payload.get("adding") == u._credentials.username:
                    if u._credentials.username not in self._active_users:
                        print(f"Adding {u._credentials.username} to active users")
                        self._active_users[u._credentials.username] = u
                        print("Updated Array")
                        return
                    
                if payload is not None and payload.get("logout") == u._credentials.username:
                    if u._credentials.username in self._active_users:
                        if u._credentials.username in self._active_connections:
                            payload = {
                                "type": "cmd",
                                "data": "rejected"
                            }
                            print(f"Sending Logout Command to {u._credentials.username}")
                            await self._active_connections[u._credentials.username].send_text(json.dumps(payload))

        
        return



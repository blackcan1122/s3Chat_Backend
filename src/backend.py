import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, APIRouter, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
import logging
from db_consts import ConversationType
from database_wrapper import DBWrapper
from db_objects import User
from datetime import datetime
import json
from envwrap import EnvParam
from pathlib import Path
import asyncio
from pydantic import BaseModel
from typing import Optional
import requests

class UserCreate(BaseModel):
    username: str
    password: str

class ApproveUserRequest(BaseModel):
    username: str

class GetOldMsgRequest(BaseModel):
    room_id: Optional[int] = None
    oldest_message: Optional[str] = None

class GroupChatRequest(BaseModel):
    user_a: str
    user_b: str

class AddParticipantReq(BaseModel):
    group_id: int
    user: str

class RemoveParticipantReq(BaseModel):
    group_id: int
    user: str

class CreateGrpReq(BaseModel):
    creator: int
    group_name: str


class Backend():

    def __init__(self, app : FastAPI, env_params : EnvParam, is_dedicated : bool = False):
        self._env = env_params
        self._app = app
        self._db = DBWrapper(db_path=self._env.ALL_PATHS.db_file)
        self._db.event_handler.add_listener(self._db.add_user_event, self.update_user_array)
        self._active_connections: list[str] = []
        self._registered_users: dict[str, User] = dict()
        self._users_to_disconnect: list[str] = []
        
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
            await incoming_user.set_id(self._db)
            if username in self._active_connections:
                payload = {
                    "type": "cmd",
                    "data": "rejected"
                }
                print(f"Sending Logout Command to {username}")
                await self._registered_users[username]._active_connection.send_text(json.dumps(payload))
                await self._registered_users[username]._active_connection.close()
                return


            try:
                result = await self._db.login(incoming_user)
            except HTTPException:
                await ws.send_json({"type": "response",
                                    "session_id": "0",
                                    "state": "AUTH_FAILED"})
                logging.error(f"Client: {ws.client} not authenticated\nUsername: {username}\nPassword:{password}")
                await ws.close()
                return
            
            current_user = self._registered_users[auth_data["username"]]
            current_user._active_connection = ws
            self._active_connections.append(current_user._credentials.username) 
            current_user._isConnected = True
            await current_user.set_id(self._db)
            sessionid = await self._db.create_session_id(current_user, datetime.now())
            is_admin = False
            if current_user._credentials.username == "Blackcan":
                is_admin = True

            payload = {
                "type": "response",
                "session_id": sessionid,
                "id": current_user._id,
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
                        if u in self._active_connections:
                            print(f"Disconnecting {u}")
                            await self._registered_users[u]._active_connection.close()
                            self._active_connections.remove(u)
                            self._registered_users[u]._isConnected = False
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
                        "room_id": 1,               # recipient's username or group id
                        "room_name": "Name"         # name of room or friend
                        "chat_type": "direct"      # or "group"
                    }
                    
                    """
                    msg = await ws.receive_json()
                    await self._db.add_message_to_history(msg, current_user)
                    relevant_users = await self._db.get_participants_from_convo(msg["room_id"])
                    for u in relevant_users:
                        try:
                            if self._registered_users[u["username"]]._active_connection is not None:
                                await self._registered_users[u["username"]]._active_connection.send_json(msg)
                        except (WebSocketDisconnect, RuntimeError):
                            self._active_connections.remove(u)
                            current_user._isConnected = False
                            current_user._active_connection = None
                            print(f"User: {current_user._credentials.username} left")
                            return
                except (WebSocketDisconnect, RuntimeError):
                    for u in self._active_connections:
                        if self._registered_users[u]._active_connection == ws:
                            self._active_connections.remove(u)
                            current_user._isConnected = False
                            current_user._active_connection = None
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
                for username, user in self._registered_users.items() if user._credentials.approved
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
            for username, user in self._registered_users.items()
            ]
        
        @router.post("/add_user", status_code=status.HTTP_201_CREATED)
        async def handle_add_user_request(User : UserCreate):
            print("we Start getting a new user")
            if User.username in self._registered_users:
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
                messages = await self._db.get_messages_from(request.room_id, request.oldest_message)
                return messages
            else:
                messages = await self._db.get_messages_from(request.room_id)
                return messages
            
        @router.post("/api/get_room")
        async def get_room(request: GroupChatRequest):
            try:
                userA = self._registered_users[request.user_a]
                userB = self._registered_users[request.user_b]
                if userA == userB:
                    formated_response = {
                        "room_id": None,
                        "old_messages": []
                    }
                    return formated_response
            except KeyError:
                raise HTTPException(status_code=404, detail="User not found")
            
            response = await self._db.retrieve_direct_convo(userA, userB)

            if response is None:
                response = await self._db.create_direct_chat(userA, userB)

            old_messages = await self._db.get_messages_from(response)
            formated_response = {
                "room_id": response,
                "old_messages": old_messages
            }
            return formated_response
        
        @router.get("/api/get_groups{username}")
        async def get_groups(username : str):
            groups = await self._db.get_user_groups(username)
            return groups
        
        @router.get("/api/get_room_msg{group_id}")
        async def get_room_msg(group_id : int):
            msg = await self._db.get_messages_from(group_id)
            return msg
        
        @router.get("/api/get_participants{group_id}")
        async def get_room_msg(group_id : int):
            msg = await self._db.get_participants_from_convo(group_id)
            return msg

        @router.get("/api/search_gifs{search_term}")
        async def search_gifs(search_term):
            self._env.TENOR_API
            limit = 8
            ckey = "S3Chat"
            if search_term is None:
                search_term = "excited"
            
            r = requests.get("https://tenor.googleapis.com/v2/search?q=%s&key=%s&client_key=%s&limit=%s" % (search_term, self._env.TENOR_API, ckey, limit))
            if r.status_code == 200:
                top_8gifs = json.loads(r.content)
                return top_8gifs
            return HTTPException(status_code=404)
        
        @router.post("/api/add_participant")
        async def add_participant_to_grp(request: AddParticipantReq):
            # Get user id from username
            user_row = await self._db.get_user(request.user)
            if not user_row:
                raise HTTPException(status_code=404, detail="User not found")
            user_id = user_row["id"]

            # Add participant to the group (conversation)
            await self._db.create_participants(request.group_id, user_id)
            return {"detail": f"User {request.user} added to group {request.group_id}"}

        @router.post("/api/remove_participant")
        async def remove_participant_from_grp(request: RemoveParticipantReq):
            # Get user id from username
            user_row = await self._db.get_user(request.user)
            if not user_row:
                raise HTTPException(status_code=404, detail="User not found")
            user_id = user_row["id"]

            # Check if user is a participant in the group
            participants = await self._db.get_participants_from_convo(request.group_id)
            print(participants)
            print(user_id)
            if not any(p.get("user_id") == user_id for p in participants):
                raise HTTPException(status_code=404, detail="User is not a participant in this group")

            # Remove participant from the group (conversation)
            await self._db.remove_participant(request.group_id, user_id)
            return {"detail": f"User {request.user} removed from group {request.group_id}"}
        
        @router.post("/api/create_group")
        async def remove_participant_from_grp(request: CreateGrpReq):
            await self._db.create_conversation(request.group_name, ConversationType.Group, request.creator)
            return {"response" : f"Group: {request.group_name} was created"}
            
            
        # catch other urls
        @router.get("/{full_path:path}", include_in_schema=False)
        async def serve_catch_all(full_path: str):
            print(full_path)
            file_path = self._env.ALL_PATHS.build / full_path
            if file_path.exists() and file_path.is_file():
                print("exist")
                return FileResponse(str(file_path))
            else:
                print("does not exist")
                raise HTTPException(status_code=404, detail="File not found")

        if is_dedicated:
            self._app.mount(
                "/static",
                StaticFiles(directory=self._env.ALL_PATHS.static, html=True),
                name="/static",
            )

        self._app.include_router(router)
        self._app.add_event_handler("startup", self.create_tables_at_startup)


    def check_token(self, payload):
        token = payload.credentials
        if token != self._env.BEARER_TOKEN:
                raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return True

    async def create_tables_at_startup(self):
        print("Starting DB Init")
        await self._db.init_db()
        users = await self._db.get_all_users()
        self._registered_users = {u._credentials.username: u for u in users}

    async def retrieve_active_users(self) -> list[User]:
        iterable_user = self._registered_users
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
                    self._registered_users[u._credentials.username] = u
                    self._registered_users[u._credentials.username]._credentials.approved = False
                    if u._credentials.username in self._active_connections:
                        payload = {
                            "type": "cmd",
                            "data": "rejected"
                        }
                        print(f"Sending Logout Command to {u._credentials.username}")
                        await self._registered_users[u._credentials.username]._active_connection.send_text(json.dumps(payload))
                    return
                
                if payload is not None and payload.get("approve") == u._credentials.username:
                    print(f"approved {u._credentials.username} from active users")
                    self._registered_users[u._credentials.username] = u
                    self._registered_users[u._credentials.username]._credentials.approved = True
                    return

                if payload is not None and payload.get("adding") == u._credentials.username:
                    if u._credentials.username not in self._registered_users:
                        print(f"Adding {u._credentials.username} to active users")
                        self._registered_users[u._credentials.username] = u
                        print("Updated Array")
                        return
                    
                if payload is not None and payload.get("logout") == u._credentials.username:
                    if u._credentials.username in self._registered_users:
                        if u._credentials.username in self._active_connections:
                            payload = {
                                "type": "cmd",
                                "data": "rejected"
                            }
                            print(f"Sending Logout Command to {u._credentials.username}")
                            await self._registered_users[u._credentials.username]._active_connection.send_text(json.dumps(payload))

        
        return



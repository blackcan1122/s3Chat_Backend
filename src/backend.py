import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, APIRouter
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
import logging
from database_wrapper import DBWrapper
from user_class import User
from datetime import datetime
import json
from envwrap import EnvParam
from pathlib import Path



class Backend():

    def __init__(self, app : FastAPI, env_params : EnvParam, is_dedicated : bool = False):
        self._env = env_params
        self._app = app
        self._db = DBWrapper(db_path=self._env.DB_PATH)
        self._active_connections: list[WebSocket] = []
        self._active_users: dict[str, User] = dict()
        
        router = APIRouter()

        @router.websocket("/ws/chat")
        async def chat(ws: WebSocket):
            print("got a MEssage")
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
                await ws.close()
                return

            current_user = self._active_users[auth_data["username"]]
            self._active_connections.append(ws)
            current_user._isConnected = True
            sessionid = await self._db.create_session_id(current_user, datetime.now())
            payload = {
                "type": "response",
                "session_id": sessionid,
                "state": "AUTH_SUCCESS"
            }

            await ws.send_text(json.dumps(payload))
            logging.info(f"Client {ws.client} authenticated as {current_user._credentials.username}")
            a : list[User] = await self.retrieve_active_users()
            for i in a:
                print(f"{i._credentials.username} is Online")

            try:
                while True:
                    msg = await ws.receive_text()
                    for conn in self._active_connections:
                        await conn.send_text(f"{current_user._credentials.username}: {msg}")
            except WebSocketDisconnect:
                self._active_connections.remove(ws)
                print(f"User: {current_user._credentials.username} left")

        @router.get("/", include_in_schema=False)
        async def serve_index():
            return FileResponse("../../frontend/index.html")


        @router.get("/{full_path:path}", include_in_schema=False)
        async def serve_catch_all(full_path: str):
            return FileResponse("../../frontend/index.html")
        
        if is_dedicated:
            self._app.mount(
                "/static",                               # URL prefix
                StaticFiles(directory="../../frontend/static", html=True),
                name="/static",
            )

        self._app.include_router(router)
        self._app.add_event_handler("startup", self.create_tables_at_startup)
        

    async def create_tables_at_startup(self):

        print("Starting DB Init")
        await self._db.init_db()
        users = await self._db.get_all_users()
        self._active_users = {u._credentials.username: u for u in users}
        for u in self._active_users:
            print(u)
            pass

    async def retrieve_active_users(self) -> dict[str, User]:
        iterable_user = self._active_users
        online_users = []
        for u in iterable_user:
            if iterable_user[u]._isConnected:
                online_users.append(iterable_user[u])
        return online_users
    
    

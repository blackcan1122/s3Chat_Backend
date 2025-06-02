from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
import logging
import sqlite3
import uvicorn
from database_wrapper import DBWrapper
from user_class import User
from datetime import datetime
import json

app = FastAPI()
db = DBWrapper()

active_connections: list[WebSocket] = []
active_users: dict[str, User] = []


# Allow React dev-server origin during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def retrieve_active_users() -> dict[str, User]:
    online_users = []
    for u in active_users:
        if active_users[u]._isConnected:
            online_users.append(active_users[u])
    return online_users
        

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("starting")
    global active_users
    users = db.get_all_users()
    active_users = {u._credentials.username: u for u in users}


    yield  # app is running

    # shutdown logic (if needed)
    print("Server shutting down...")

app = FastAPI(lifespan=lifespan)

@app.websocket("/ws/chat")
async def chat(ws: WebSocket):
    await ws.accept()
    auth_data = await ws.receive_json()
    
    try:
        current_user = active_users[auth_data["username"]]
        print(current_user._credentials)
        result = await db.login(current_user)
    except HTTPException:
        payload = {
        "type": "response",
        "session_id": "0",
        "state": "AUTH_FAILED"
        }
        await ws.send_text(json.dumps(payload))
        print("closing websocket")
        await ws.close()
        return
        
    active_connections.append(ws)
    current_user._isConnected = True
    sessionid = db.create_session_id(current_user, datetime.now().hour)
    payload = {
        "type": "response",
        "session_id": sessionid,
        "state": "AUTH_SUCCESS"
    }
    await ws.send_text(json.dumps(payload))
    logging.info(f"Client {ws.client} authenticated as {current_user._credentials.username}")
    a : list[User] = await retrieve_active_users()
    for i in a:
        print(f"{i._credentials.username} is Online")

    try:
        while True:
            msg = await ws.receive_text()
            for conn in active_connections:
                await conn.send_text(f"{current_user._credentials.username}: {msg}")
    except WebSocketDisconnect:
        active_connections.remove(ws)
        print(f"User: {current_user._credentials.username} left")

if __name__ == "__main__":
    db._init_db()
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
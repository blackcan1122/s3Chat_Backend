
import os
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
import logging
import sqlite3
from user_class import Credentials
import uvicorn
from database_wrapper import DBWrapper
from user_class import User
from datetime import datetime
import json

from database_wrapper import DBWrapper  # or wherever you keep your DB code

db = DBWrapper()
active_connections: list[WebSocket] = []
active_users: dict[str, User] = []

async def retrieve_active_users() -> dict[str, User]:
    online_users = []
    for u in active_users:
        if active_users[u]._isConnected:
            online_users.append(active_users[u])
    return online_users

# Lifecycle: initialize DB once at startup
async def create_tables_at_startup():
    print("started DB creation")
    await db.init_db()
    print("starting")
    global active_users
    users = await db.get_all_users()
    print(users)
    active_users = {u._credentials.username: u for u in users}
    for u in active_users:
        print(u)

app = FastAPI(on_startup=[create_tables_at_startup])

#
# 1) Mount the React “build” directory under a dedicated prefix for static assets:
#
app.mount(
    "/static",
    StaticFiles(directory="../../frontend/static"),  # CSS/JS under “static/…”
    name="static",
)

#
# 2) Serve index.html at root (/) so that the React app loads:
#
@app.get("/", include_in_schema=False)
async def serve_index():
    return FileResponse("../../frontend/index.html")

#
# 3) If you expect people to deep‐link (e.g. /some/react/route),
#    add a “catch‐all” that returns index.html for any unrecognized path—
#    but do NOT override your API or WebSocket endpoints. For example:
#
@app.get("/{full_path:path}", include_in_schema=False)
async def serve_catch_all(full_path: str):
    # If the requested path starts with “api/” or “ws/”, 
    # FastAPI would already have routed to your endpoints. 
    # Any other path (e.g. /chat, /about) should just get index.html:
    return FileResponse("../../frontend/index.html")


#
# 4) Your WebSocket / REST endpoints go here:
#
@app.websocket("/ws/chat")
async def chat(ws: WebSocket):
    await ws.accept()
    auth_data = await ws.receive_json()
    
# 1. Build credentials exactly as the client supplied them

    username   = auth_data.get("username", "")
    password   = auth_data.get("password", "")
    session_id = auth_data.get("session_id", "")
    print(username)
    print(password)
    print(session_id)
    incoming_user = User(username, password, session_id)
    print(incoming_user)
    # 2. Let the DB wrapper validate them
    try:
        result = await db.login(incoming_user)
    except HTTPException:
        await ws.send_json({"type": "response",
                            "session_id": "0",
                            "state": "AUTH_FAILED"})
        print("HTTP Exception in db login")
        await ws.close()
        return
    
    current_user = active_users[auth_data["username"]]
    active_connections.append(ws)
    current_user._isConnected = True
    sessionid = await db.create_session_id(current_user, datetime.now())
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


# (Any other /api/ routes live above this point)
#

#
# 5) Run via Uvicorn on 0.0.0.0 and a PORT from env:
#
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main_dedicated:app",
        host="216.201.76.168",
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )

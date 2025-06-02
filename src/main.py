from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
import logging
from pydantic import BaseModel
import sqlite3
import uvicorn


app = FastAPI()

authenticated_users = ["MARCEL"]

# Allow React dev-server origin during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# User model
class LoginRequest(BaseModel):
    username: str
    password: str
    
# Endpoint for login
@app.post("/login")
async def login(request: LoginRequest):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
    "SELECT * FROM users WHERE username=? AND password=? AND approved=1",
    (request.username, request.password))
    user = cursor.fetchone()
    conn.close()

    if user:
        return {"status": "success", "username": user["username"]}
    raise HTTPException(status_code=401, detail="Invalid credentials")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup logic
    

    yield  # app is running

    # shutdown logic (if needed)
    print("Server shutting down...")

app = FastAPI(lifespan=lifespan)

active_connections: list[WebSocket] = []

@app.websocket("/ws/chat")
async def chat(ws: WebSocket):
    await ws.accept()
    try:
        auth_msg = await ws.receive_text()
        if auth_msg not in authenticated_users:
            logging.error(f"Client {ws.client} rejected with auth: {auth_msg}")
            await ws.send_text("AUTH_FAILED")
            await ws.close()
            return

        # Add to active connections only after successful auth
        active_connections.append(ws)
        await ws.send_text("AUTH_SUCCESS")
        logging.info(f"Client {ws.client} authenticated as {auth_msg}")

        # Main chat loop
        while True:
            msg = await ws.receive_text()
            for conn in active_connections:
                await conn.send_text(f"{auth_msg}: {msg}")

    except WebSocketDisconnect:
        if ws in active_connections:
            active_connections.remove(ws)
        logging.info("Client %s disconnected", ws.client)

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
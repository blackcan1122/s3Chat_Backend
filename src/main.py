from envwrap import EnvParam
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv
from backend import Backend
import os
import argparse


    



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start the S3Chat backend server.")
    parser.add_argument("-dedicated", action="store_true", help="Deployment")
    args = parser.parse_args()

    if args.dedicated:
        print("Loading Dedicated Settings")
        if load_dotenv(".env.production") == False:
            print("OH OH")
    else:
        print("Loading Local Settings")    
        if load_dotenv(".env") == False:
            print("OH OH")

    HOST = os.getenv("BACKEND_HOST", "127.0.0.1")
    PORT = int(os.getenv("BACKEND_PORT", 8000))
    DB_PATH = os.getenv("DB_PATH", "database.db")
    ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

    CurrentEnv = EnvParam(HOST=HOST, PORT=PORT, DB_PATH=DB_PATH, ALLOWED_ORIGINS=ALLOWED_ORIGINS)
    print(f"Using Following Settings for Server Setup:{CurrentEnv}")

    ORIGINS = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    app = FastAPI()
    if args.dedicated is False:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    CurrentBackend = Backend(app, CurrentEnv, args.dedicated)
    uvicorn.run(CurrentBackend._app, host=CurrentEnv.HOST, port=CurrentEnv.PORT, reload=False)
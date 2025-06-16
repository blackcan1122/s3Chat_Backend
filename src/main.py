from envwrap import EnvParam
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv
from backend import Backend
import os
import argparse
from paths import PathWrap
import logging
from datetime import datetime

if __name__ == "__main__":
    CurrentPaths = PathWrap()
    CurrentPaths.validate_all_paths()
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
    ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    BEARER_TOKEN = os.getenv("BEARER_TOKEN")

    CurrentEnv = EnvParam(HOST=HOST, PORT=PORT, ALL_PATHS=CurrentPaths, ALLOWED_ORIGINS=ALLOWED_ORIGINS, BEARER_TOKEN=BEARER_TOKEN)
    print(f"Using Following Settings for Server Setup:{CurrentEnv}")

    app = FastAPI()
    if args.dedicated is False:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=CurrentEnv.ALLOWED_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
    log_filename = f"uvicorn_{datetime.now().strftime('%Y-%m-%d')}.log"
    
    logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler()
            ]
    )
    CurrentBackend = Backend(app, CurrentEnv, args.dedicated)
    uvicorn.run(CurrentBackend._app, host=CurrentEnv.HOST, port=CurrentEnv.PORT, reload=False)
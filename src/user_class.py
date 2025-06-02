from pydantic import BaseModel

class Credentials(BaseModel):
    username: str
    password: str
    session_id: str

class User():
    def __init__(self, username: str, password: str, session_id : str = ""):
        self._credentials = Credentials(username=username, password=password, session_id = session_id)
        self._isConnected = False

    def set_credentials(self, cred: Credentials):
        self._credentials = Credentials(**cred.model_dump())

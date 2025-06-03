from dataclasses import dataclass

@dataclass
class EnvParam():
    HOST : str
    PORT : str
    DB_PATH : str
    ALLOWED_ORIGINS : str
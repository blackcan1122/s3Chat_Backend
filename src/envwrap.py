from dataclasses import dataclass
from paths import PathWrap

@dataclass
class EnvParam():
    HOST : str
    PORT : str
    ALLOWED_ORIGINS : str
    ALL_PATHS : PathWrap
    BEARER_TOKEN : str
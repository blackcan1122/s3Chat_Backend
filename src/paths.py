from pathlib import Path
from dataclasses import dataclass

@dataclass
class PathWrap():
    """
    Path constants for the whole project.
    Everything is relative to the git-root S3Chat_All/, no matter where you 'cd'.
    """
    _here:      Path = Path(__file__).resolve()
    root:       Path = _here.parents[2]

    backend:    Path = root / "S3Chat_backend"
    frontend:   Path = root / "S3Chat"
    public:     Path = frontend / "public"
    build:      Path = frontend / "build"
    static:     Path = build / "static"

    db_file:    Path = backend / "database.db"

    paths_to_validate = [_here, root, backend, frontend, public, build, static]

    def validate_all_paths(self):
        state = True
        for i in self.paths_to_validate:
            if not i.exists():
                raise FileNotFoundError(f"Path does not exist: {i}")
            




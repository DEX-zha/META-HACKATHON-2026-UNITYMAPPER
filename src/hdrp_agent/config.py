from dataclasses import dataclass, field
import os
from pathlib import Path
import secrets

from .domain import AgentError


def contained(root: Path, path: Path) -> Path:
    root = root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise AgentError("OUT_OF_SCOPE", "Path is outside the registered root", 422)
    return resolved


@dataclass
class Settings:
    workspace: Path
    provider_mode: str = "offline"
    api_key: str | None = field(default=None, repr=False)
    token: str = field(default="", repr=False)

    def __post_init__(self):
        self.workspace = self.workspace.resolve()
        if self.provider_mode not in {"offline", "live"}: raise ValueError("Invalid provider mode")
        self.state = contained(self.workspace, self.workspace / ".hdrp-agent")
        self.state.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state / "global.sqlite3"
        path = self.state / "local-token"
        if not self.token:
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as stream: stream.write(secrets.token_urlsafe(32))
            except FileExistsError:
                pass
            if path.is_symlink(): raise AgentError("OUT_OF_SCOPE", "Local token cannot be a symlink")
            self.token = path.read_text().strip()
            path.chmod(0o600)
        if not self.token: raise ValueError("Empty local token")

    def project_path(self, path: str):
        resolved = contained(self.workspace, Path(path))
        if not resolved.is_dir(): raise AgentError("NOT_FOUND", "Project directory does not exist", 404)
        return resolved

    @classmethod
    def load(cls, workspace, provider_mode="offline", env_file=None):
        values = {}
        if env_file is not None:
            from dotenv import dotenv_values
            path = contained(Path(workspace), Path(env_file))
            values = dotenv_values(path)
        key = os.environ.get("MODEL_API_KEY") or os.environ.get("API_KEY") or values.get("MODEL_API_KEY") or values.get("API_KEY")
        return cls(Path(workspace), provider_mode, key)

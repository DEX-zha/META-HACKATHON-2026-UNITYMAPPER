import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from contextlib import closing

from .config import contained
from .domain import AgentError, canonical


class ArtifactStore:
    def __init__(self, root: Path, store):
        self.root, self.store = contained(store.path.parent, Path(root)), store
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, digest):
        if not re.fullmatch(r"[a-f0-9]{64}", digest): raise AgentError("INVALID_HASH", "Invalid artifact digest", 422)
        return contained(self.root, self.root / digest[:2] / digest)

    def put(self, data: bytes, media_type="application/octet-stream", expected=None, metadata=None):
        limit = 20_000_000 if media_type in {"video/mp4", "application/octet-stream"} else 10_000_000
        if len(data) > limit: raise AgentError("PAYLOAD_TOO_LARGE", "Artifact exceeds its size limit", 413)
        digest = hashlib.sha256(data).hexdigest()
        if expected is not None and digest != expected: raise AgentError("HASH_MISMATCH", "Artifact bytes do not match their digest", 422)
        target = self.path(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            fd, name = tempfile.mkstemp(dir=target.parent, prefix=".writing-")
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data); stream.flush(); os.fsync(stream.fileno())
                os.replace(name, target)
            finally:
                if os.path.exists(name): os.unlink(name)
        elif hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise AgentError("CORRUPT_ARTIFACT", "Existing artifact has a corrupt digest")
        body = {"hash": digest, "media_type": media_type, "metadata": metadata or {}}
        with self.store.tx() as conn:
            conn.execute("INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?)", (digest, len(data), media_type, canonical(body)))
        return digest

    def read(self, digest):
        target = self.path(digest)
        with closing(self.store.connect()) as conn:
            row = conn.execute("SELECT hash FROM artifacts WHERE hash=?", (digest,)).fetchone()
        if not row or not target.is_file(): raise AgentError("NOT_FOUND", "Artifact does not exist", 404)
        data = target.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest: raise AgentError("CORRUPT_ARTIFACT", "Artifact digest failed")
        return data

    def cache_get(self, key):
        with closing(self.store.connect()) as conn:
            row = conn.execute("SELECT artifact_hash FROM cache WHERE key=?", (key,)).fetchone()
        return row["artifact_hash"] if row else None

    def cache_put(self, key, digest):
        self.read(digest)
        with self.store.tx() as conn:
            conn.execute("INSERT INTO cache VALUES(?,?) ON CONFLICT(key) DO UPDATE SET artifact_hash=excluded.artifact_hash", (key, digest))

"""Local durable state. Transactions never include network or Unity work."""

from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import uuid

from .domain import AgentError, canonical, fingerprint


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex}"


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, epoch TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scenes(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), scene_id TEXT NOT NULL REFERENCES scenes(id), state TEXT NOT NULL, body TEXT NOT NULL, stop_requested INTEGER NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_session ON sessions((1)) WHERE state NOT IN ('completed','limit_reached','interrupted');
CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id), project_id TEXT NOT NULL REFERENCES projects(id), epoch TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL, body TEXT NOT NULL, payload_hash TEXT NOT NULL, result TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0, heartbeat TEXT);
CREATE INDEX IF NOT EXISTS commands_by_project ON commands(project_id,status);
CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY, scene_id TEXT NOT NULL REFERENCES scenes(id), body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS artifacts(hash TEXT PRIMARY KEY, bytes INTEGER NOT NULL, media_type TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, artifact_hash TEXT NOT NULL REFERENCES artifacts(hash));
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS idempotency(scope TEXT NOT NULL, key TEXT NOT NULL, request_hash TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(scope,key));
CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY, model TEXT NOT NULL, payload_hash TEXT NOT NULL, status TEXT NOT NULL, reserved INTEGER NOT NULL CHECK(reserved>=0), actual INTEGER, pricing TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS budget_entries(id TEXT PRIMARY KEY, call_id TEXT REFERENCES calls(id), kind TEXT NOT NULL, amount INTEGER NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS budget_envelopes(name TEXT PRIMARY KEY, cap INTEGER NOT NULL CHECK(cap>=0));
CREATE TABLE IF NOT EXISTS envelope_calls(name TEXT NOT NULL REFERENCES budget_envelopes(name), call_id TEXT NOT NULL UNIQUE REFERENCES calls(id), PRIMARY KEY(name,call_id));
"""


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        if self.path.is_symlink(): raise AgentError('OUT_OF_SCOPE', 'Durable database cannot be a symlink')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as conn:
            conn.executescript(SCHEMA)
            version=conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if version and version[0]=='1':
                if conn.execute('SELECT 1 FROM calls LIMIT 1').fetchone() or conn.execute('SELECT 1 FROM budget_entries LIMIT 1').fetchone():
                    raise AgentError('CURRENCY_MIGRATION_REQUIRED','A populated EUR ledger requires explicit accounting conversion')
                backup=self.path.with_name(self.path.name+'.eur-v1-backup')
                if not backup.exists():
                    with closing(sqlite3.connect(backup)) as archived:conn.backup(archived)
                    backup.chmod(0o600)
                old=dict(conn.execute('SELECT key,value FROM meta').fetchall())
                conn.execute('INSERT OR IGNORE INTO meta VALUES(?,?)',('legacy_eur_meta',canonical(old)))
                conn.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
                conn.execute("UPDATE meta SET value='required' WHERE key='reconciliation_state'")
            for key, value in {"schema_version": "2", "currency":"USD", "cap_usd_micro": "150000000", "external_total": "0", "reconciliation_state": "required"}.items():
                conn.execute("INSERT OR IGNORE INTO meta VALUES(?,?)", (key, value))
            if conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] != '2':
                raise AgentError('SCHEMA_VERSION', 'Unsupported durable storage schema')
        self.path.chmod(0o600)

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    @contextmanager
    def tx(self, existing=None):
        if existing is not None:
            yield existing
            return
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction: conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def event(self, conn, subject, kind, body):
        conn.execute("INSERT INTO events(subject,kind,body,created_at) VALUES(?,?,?,?)", (subject, kind, canonical(body), utc_now()))

    def get(self, table, key):
        if table not in {"projects", "scenes", "sessions", "versions", "commands"}: raise ValueError("Unknown table")
        with closing(self.connect()) as conn:
            row = conn.execute(f"SELECT body FROM {table} WHERE id=?", (key,)).fetchone()
        if not row: raise AgentError("NOT_FOUND", "Resource does not exist", 404)
        return json.loads(row["body"])

    def idempotent(self, scope, key, request, action):
        if not key or len(key) > 200: raise AgentError("INVALID_IDEMPOTENCY_KEY", "A bounded Idempotency-Key is required", 422)
        digest = fingerprint(request)
        with self.tx() as conn:
            row = conn.execute("SELECT * FROM idempotency WHERE scope=? AND key=?", (scope, key)).fetchone()
            if row:
                if row["request_hash"] != digest: raise AgentError("IDEMPOTENCY_CONFLICT", "Key was used with a different request")
                return json.loads(row["response"])
            response = action(conn)
            conn.execute("INSERT INTO idempotency VALUES(?,?,?,?)", (scope, key, digest, canonical(response)))
            return response

    def update_session(self, conn, session_id, **changes):
        row = conn.execute("SELECT body FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not row: raise AgentError("NOT_FOUND", "Session does not exist", 404)
        data = json.loads(row["body"])
        data.update(changes)
        conn.execute("UPDATE sessions SET state=?,body=? WHERE id=?", (data["state"], canonical(data), session_id))
        self.event(conn, session_id, "session_updated", changes)
        return data

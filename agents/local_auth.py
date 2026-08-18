"""Minimal local username/password authentication for trusted test deployments."""

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Optional


SESSION_TTL_SECONDS = int(os.getenv("LOCAL_AUTH_SESSION_TTL", str(12 * 3600)))


class LocalAuthStore:
    def __init__(self, database_path: str = "data/local_auth.db"):
        self.database_path = database_path
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._bootstrap_users()

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self):
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS local_users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    disabled INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS local_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES local_users(user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_local_sessions_expiry
                    ON local_sessions(expires_at);
            """)

    @staticmethod
    def _hash_password(password: str, salt: Optional[bytes] = None) -> str:
        salt = salt or secrets.token_bytes(16)
        iterations = 310_000
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
        return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"

    @classmethod
    def _verify_password(cls, password: str, encoded: str) -> bool:
        try:
            algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
            ).hex()
            return hmac.compare_digest(actual, digest_hex)
        except (TypeError, ValueError):
            return False

    def _bootstrap_users(self):
        """Create initial users from LOCAL_AUTH_USERS once.

        Format: JSON object, e.g. {"alice": "password", "bob": "password"}.
        Passwords are only used during bootstrap and are stored as hashes.
        """
        raw = os.getenv("LOCAL_AUTH_USERS", "").strip()
        if not raw:
            return
        try:
            users = json.loads(raw)
            if not isinstance(users, dict):
                raise ValueError
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError("LOCAL_AUTH_USERS must be a JSON object of username/password pairs") from exc
        now = int(time.time())
        with self._connect() as db:
            for username, password in users.items():
                if not isinstance(username, str) or not isinstance(password, str) or not password:
                    raise RuntimeError("LOCAL_AUTH_USERS contains an invalid user")
                db.execute(
                    "INSERT OR IGNORE INTO local_users(user_id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
                    (username, username, self._hash_password(password), now),
                )

    def authenticate(self, username: str, password: str) -> Optional[str]:
        with self._connect() as db:
            row = db.execute(
                "SELECT user_id, password_hash FROM local_users WHERE username = ? AND disabled = 0",
                (username,),
            ).fetchone()
        if row and self._verify_password(password, row["password_hash"]):
            return str(row["user_id"])
        return None

    def create_session(self, user_id: str) -> str:
        session_id = secrets.token_urlsafe(32)
        now = int(time.time())
        with self._connect() as db:
            db.execute("DELETE FROM local_sessions WHERE expires_at < ?", (now,))
            db.execute(
                "INSERT INTO local_sessions(session_id, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (session_id, user_id, now + SESSION_TTL_SECONDS, now),
            )
        return session_id

    def get_user_id(self, session_id: Optional[str]) -> Optional[str]:
        if not session_id:
            return None
        now = int(time.time())
        with self._connect() as db:
            row = db.execute(
                "SELECT user_id FROM local_sessions WHERE session_id = ? AND expires_at > ?",
                (session_id, now),
            ).fetchone()
        return str(row["user_id"]) if row else None

    def revoke_session(self, session_id: Optional[str]):
        if session_id:
            with self._connect() as db:
                db.execute("DELETE FROM local_sessions WHERE session_id = ?", (session_id,))


local_auth_store = LocalAuthStore(os.getenv("LOCAL_AUTH_DB", "data/local_auth.db"))


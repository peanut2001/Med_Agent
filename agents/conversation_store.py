"""Persistent conversation history for the local deployment.

Threads and their messages live in a SQLite file, mirroring the storage style
already used by ``local_auth``: nothing extra to run, and every row is scoped
to the user id that owns it.  The LangGraph checkpointer keeps the model's
working memory; this store keeps what the user should still see after a
refresh or a restart.
"""

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_TITLE = "新对话"
TITLE_MAX_LENGTH = 40
MESSAGE_ROLES = {"user", "assistant", "system"}
MAX_LIST_LIMIT = 500


def build_title(content: str) -> str:
    """Derive a thread title from its first user message."""
    text = " ".join((content or "").split())
    return text[:TITLE_MAX_LENGTH] if text else DEFAULT_TITLE


class ConversationStore:
    def __init__(self, database_path: str = "data/conversations.db"):
        self.database_path = database_path
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _init_db(self):
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_conversations_user
                    ON conversations(user_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    agent TEXT,
                    status_label TEXT,
                    content TEXT NOT NULL,
                    result_image TEXT,
                    has_image INTEGER NOT NULL DEFAULT 0,
                    validation_id TEXT,
                    validation_request_id TEXT,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_conversation_messages_thread
                    ON conversation_messages(conversation_id, message_id);
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(conversation_messages)")}
            if "validation_id" not in columns:
                db.execute("ALTER TABLE conversation_messages ADD COLUMN validation_id TEXT")
            if "validation_request_id" not in columns:
                db.execute("ALTER TABLE conversation_messages ADD COLUMN validation_request_id TEXT")
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_validation "
                "ON conversation_messages(validation_id) WHERE validation_id IS NOT NULL"
            )

    @staticmethod
    def _owned(db, conversation_id: str, user_id: str) -> Optional[sqlite3.Row]:
        """Return the thread row, or None when it does not exist yet.

        Raises PermissionError rather than 404 semantics when the thread
        exists but belongs to somebody else, so a guessed id cannot be used
        to probe another account's history.
        """
        row = db.execute(
            "SELECT conversation_id, user_id, title FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            return None
        if row["user_id"] != user_id:
            raise PermissionError("conversation_owned_by_another_user")
        return row

    def check_access(self, conversation_id: str, *, user_id: str, require_exists: bool = False) -> None:
        """Allow new IDs, but reject an existing conversation owned by somebody else."""
        with self._connect() as db:
            if self._owned(db, conversation_id, user_id) is None and require_exists:
                raise KeyError("conversation_not_found")

    def append_validation(self, *, user_id: str, conversation_id: str,
                          validation_id: str, content: str, status_label: str) -> None:
        """Persist a review once, without recreating a deleted conversation."""
        now = int(time.time())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if self._owned(db, conversation_id, user_id) is None:
                raise KeyError("conversation_not_found")
            inserted = db.execute(
                "INSERT OR IGNORE INTO conversation_messages "
                "(conversation_id, role, agent, status_label, content, created_at, validation_id) "
                "VALUES (?, 'assistant', 'HUMAN_VALIDATED', ?, ?, ?, ?)",
                (conversation_id, status_label, content, now, validation_id),
            )
            if inserted.rowcount:
                db.execute("UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                           (now, conversation_id))

    def append(
        self,
        *,
        user_id: str,
        conversation_id: str,
        role: str,
        content: str,
        agent: Optional[str] = None,
        status_label: Optional[str] = None,
        result_image: Optional[str] = None,
        has_image: bool = False,
        validation_request_id: Optional[str] = None,
    ) -> None:
        if role not in MESSAGE_ROLES:
            raise ValueError(f"Unsupported message role: {role}")
        now = int(time.time())
        with self._connect() as db:
            existing = self._owned(db, conversation_id, user_id)
            if existing is None:
                db.execute(
                    "INSERT INTO conversations(conversation_id, user_id, title, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        conversation_id,
                        user_id,
                        build_title(content) if role == "user" else DEFAULT_TITLE,
                        now,
                        now,
                    ),
                )
            else:
                # A thread opened by a system/assistant message still carries the
                # placeholder title; the first user message names it for real.
                if role == "user" and existing["title"] == DEFAULT_TITLE:
                    db.execute(
                        "UPDATE conversations SET title = ? WHERE conversation_id = ?",
                        (build_title(content), conversation_id),
                    )
                db.execute(
                    "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                    (now, conversation_id),
                )
            db.execute(
                "INSERT INTO conversation_messages(conversation_id, role, agent, status_label,"
                " content, result_image, has_image, created_at, validation_request_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    conversation_id,
                    role,
                    agent,
                    status_label,
                    content,
                    result_image,
                    1 if has_image else 0,
                    now,
                    validation_request_id,
                ),
            )

    def list_for_user(self, user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT c.conversation_id, c.title, c.created_at, c.updated_at,"
                " (SELECT COUNT(*) FROM conversation_messages m"
                "  WHERE m.conversation_id = c.conversation_id) AS message_count"
                " FROM conversations c WHERE c.user_id = ?"
                " ORDER BY c.updated_at DESC, c.rowid DESC LIMIT ?",
                (user_id, max(1, min(limit, MAX_LIST_LIMIT))),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_messages(self, conversation_id: str, *, user_id: str) -> List[Dict[str, Any]]:
        with self._connect() as db:
            if self._owned(db, conversation_id, user_id) is None:
                raise KeyError("conversation_not_found")
            rows = db.execute(
                "SELECT message_id, role, agent, status_label, content, result_image,"
                " has_image, created_at, validation_request_id FROM conversation_messages"
                " WHERE conversation_id = ? ORDER BY message_id",
                (conversation_id,),
            ).fetchall()
        return [{**dict(row), "has_image": bool(row["has_image"])} for row in rows]

    def get_recent_messages(self, conversation_id: str, *, user_id: str, limit: int) -> List[Dict[str, Any]]:
        """Read a bounded, owned history window for checkpoint recovery."""
        with self._connect() as db:
            if self._owned(db, conversation_id, user_id) is None:
                return []
            rows = db.execute(
                "SELECT message_id, role, content FROM conversation_messages "
                "WHERE conversation_id = ? ORDER BY message_id DESC LIMIT ?",
                (conversation_id, max(1, limit)),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def rename(self, conversation_id: str, *, user_id: str, title: str) -> Dict[str, Any]:
        clean = " ".join((title or "").split())[:TITLE_MAX_LENGTH]
        if not clean:
            raise ValueError("Title must not be empty")
        with self._connect() as db:
            if self._owned(db, conversation_id, user_id) is None:
                raise KeyError("conversation_not_found")
            db.execute(
                "UPDATE conversations SET title = ? WHERE conversation_id = ?",
                (clean, conversation_id),
            )
        return {"conversation_id": conversation_id, "title": clean}

    def delete(self, conversation_id: str, *, user_id: str) -> None:
        with self._connect() as db:
            if self._owned(db, conversation_id, user_id) is None:
                raise KeyError("conversation_not_found")
            db.execute(
                "DELETE FROM conversation_messages WHERE conversation_id = ?",
                (conversation_id,),
            )
            db.execute(
                "DELETE FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            )


conversation_store = ConversationStore(os.getenv("CONVERSATION_DB", "data/conversations.db"))

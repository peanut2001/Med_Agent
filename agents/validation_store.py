"""Small validation repository with a safe in-process fallback.

The in-memory implementation keeps the project runnable without a database;
production should set CHECKPOINT_DATABASE_URL and replace this repository with
the SQL-backed adapter introduced in the same interface.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from threading import RLock
from typing import Dict, Optional
import os
import uuid


@dataclass
class ValidationRecord:
    validation_id: str
    user_id: str
    conversation_id: str
    thread_id: str
    agent_name: str
    original_output: str
    result_image_path: Optional[str] = None
    status: str = "pending"
    comments: Optional[str] = None
    created_at: str = ""
    resolved_at: Optional[str] = None


class ValidationStore:
    def __init__(self):
        self._records: Dict[str, ValidationRecord] = {}
        self._lock = RLock()
        self._engine = None
        database_url = os.getenv("CHECKPOINT_DATABASE_URL", "").strip()
        if database_url:
            try:
                from sqlalchemy import create_engine, text
                self._engine = create_engine(database_url, future=True, pool_pre_ping=True)
                with self._engine.begin() as conn:
                    conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS medical_validations (
                            validation_id VARCHAR(64) PRIMARY KEY,
                            user_id VARCHAR(255) NOT NULL,
                            conversation_id VARCHAR(255) NOT NULL,
                            thread_id VARCHAR(512) NOT NULL,
                            agent_name VARCHAR(255) NOT NULL,
                            original_output TEXT NOT NULL,
                            result_image_path TEXT,
                            status VARCHAR(32) NOT NULL,
                            comments TEXT,
                            created_at VARCHAR(64) NOT NULL,
                            resolved_at VARCHAR(64)
                        )
                    """))
            except Exception:
                # Do not hide an invalid production database configuration.
                self._engine = None
                raise

    @staticmethod
    def _from_mapping(row) -> ValidationRecord:
        return ValidationRecord(**dict(row))

    def create(self, *, user_id: str, conversation_id: str, thread_id: str,
               agent_name: str, original_output: str,
               result_image_path: Optional[str] = None) -> ValidationRecord:
        record = ValidationRecord(
            validation_id=str(uuid.uuid4()), user_id=user_id,
            conversation_id=conversation_id, thread_id=thread_id,
            agent_name=agent_name, original_output=original_output,
            result_image_path=result_image_path,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        if self._engine is not None:
            from sqlalchemy import text
            with self._engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO medical_validations
                    (validation_id, user_id, conversation_id, thread_id, agent_name,
                     original_output, result_image_path, status, comments, created_at, resolved_at)
                    VALUES (:validation_id, :user_id, :conversation_id, :thread_id, :agent_name,
                            :original_output, :result_image_path, :status, :comments, :created_at, :resolved_at)
                """), asdict(record))
        else:
            with self._lock:
                self._records[record.validation_id] = record
        return record

    def resolve(self, validation_id: str, *, user_id: str, conversation_id: str,
                result: str, comments: Optional[str] = None) -> ValidationRecord:
        if self._engine is not None:
            from sqlalchemy import text
            with self._engine.begin() as conn:
                row = conn.execute(text("SELECT * FROM medical_validations WHERE validation_id = :id"), {"id": validation_id}).mappings().first()
                record = self._from_mapping(row) if row else None
                if record is None:
                    raise KeyError("validation_not_found")
                if record.user_id != user_id or record.conversation_id != conversation_id:
                    raise PermissionError("validation_forbidden")
                if record.status == "pending":
                    record.status = "approved" if result.lower() == "yes" else "rejected"
                    record.comments = comments
                    record.resolved_at = datetime.now(timezone.utc).isoformat()
                    conn.execute(text("""
                        UPDATE medical_validations
                        SET status = :status, comments = :comments, resolved_at = :resolved_at
                        WHERE validation_id = :validation_id
                    """), asdict(record))
                return record
        with self._lock:
            record = self._records.get(validation_id)
            if record is None:
                raise KeyError("validation_not_found")
            if record.user_id != user_id or record.conversation_id != conversation_id:
                raise PermissionError("validation_forbidden")
            if record.status != "pending":
                return record  # idempotent retry
            record.status = "approved" if result.lower() == "yes" else "rejected"
            record.comments = comments
            record.resolved_at = datetime.now(timezone.utc).isoformat()
            return record

    def get(self, validation_id: str) -> Optional[ValidationRecord]:
        if self._engine is not None:
            from sqlalchemy import text
            with self._engine.connect() as conn:
                row = conn.execute(text("SELECT * FROM medical_validations WHERE validation_id = :id"), {"id": validation_id}).mappings().first()
                return self._from_mapping(row) if row else None
        with self._lock:
            return self._records.get(validation_id)


validation_store = ValidationStore()

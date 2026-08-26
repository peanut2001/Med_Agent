"""Thread-safe, privacy-preserving execution traces for LangGraph requests."""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
import os
from threading import RLock
import time
from typing import Any, Callable, Dict, Iterator, Optional, TypeVar
import uuid


T = TypeVar("T")
_active_trace_id: ContextVar[Optional[str]] = ContextVar("active_trace_id", default=None)


NODE_LABELS = {
    "analyze_input": "输入分析与安全检查",
    "route_to_agent": "智能体路由决策",
    "CONVERSATION_AGENT": "通用对话智能体",
    "RAG_AGENT": "医学知识检索智能体",
    "WEB_SEARCH_PROCESSOR_AGENT": "联网检索智能体",
    "BRAIN_TUMOR_AGENT": "脑部影像智能体",
    "CHEST_XRAY_AGENT": "胸片分析智能体",
    "SKIN_LESION_AGENT": "皮肤病灶智能体",
    "check_validation": "人工复核判定",
    "human_validation": "创建人工复核任务",
    "apply_guardrails": "输出安全检查",
}


def _bounded_env_int(name: str, default: int, minimum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value)


class ExecutionTraceStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._records: Dict[str, Dict[str, Any]] = {}
        self._ttl_seconds = _bounded_env_int("EXECUTION_TRACE_TTL_SECONDS", 3600, 300)
        self._max_records = _bounded_env_int("EXECUTION_TRACE_MAX_RECORDS", 1000, 100)

    def _prune_locked(self) -> None:
        cutoff = time.monotonic() - self._ttl_seconds
        expired = [
            trace_id
            for trace_id, record in self._records.items()
            if record["started_monotonic"] < cutoff
        ]
        for trace_id in expired:
            self._records.pop(trace_id, None)
        overflow = len(self._records) - self._max_records
        if overflow > 0:
            oldest = sorted(
                self._records.items(), key=lambda item: item[1]["started_monotonic"]
            )[:overflow]
            for trace_id, _ in oldest:
                self._records.pop(trace_id, None)

    def create(self, *, user_id: str, conversation_id: str) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "trace_id": str(uuid.uuid4()),
            "user_id": user_id,
            "conversation_id": conversation_id,
            "status": "queued",
            "started_at": now,
            "started_monotonic": time.monotonic(),
            "finished_at": None,
            "total_duration_ms": None,
            "nodes": [],
        }
        with self._lock:
            self._prune_locked()
            self._records[record["trace_id"]] = record
        return self._public(record)

    def activate(self, trace_id: str, *, user_id: str, conversation_id: str) -> None:
        with self._lock:
            record = self._records.get(trace_id)
            if (
                record is None
                or record["user_id"] != user_id
                or record["conversation_id"] != conversation_id
            ):
                raise KeyError("trace_not_found")
            if record["status"] != "queued":
                raise ValueError("trace_already_used")
            record["status"] = "running"

    def start_node(self, trace_id: str, node_id: str) -> Optional[str]:
        event_id = str(uuid.uuid4())
        with self._lock:
            record = self._records.get(trace_id)
            if record is None:
                return None
            record["nodes"].append({
                "event_id": event_id,
                "node_id": node_id,
                "label": NODE_LABELS.get(node_id, node_id),
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "started_monotonic": time.monotonic(),
                "duration_ms": None,
                "metadata": {},
            })
        return event_id

    def finish_node(
        self,
        trace_id: str,
        event_id: Optional[str],
        *,
        status: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if event_id is None:
            return
        with self._lock:
            record = self._records.get(trace_id)
            if record is None:
                return
            event = next(
                (item for item in record["nodes"] if item["event_id"] == event_id),
                None,
            )
            if event is None:
                return
            event["status"] = status
            event["duration_ms"] = round(
                (time.monotonic() - event["started_monotonic"]) * 1000, 1
            )
            event["metadata"] = metadata or {}

    def finish(self, trace_id: str, *, status: str) -> None:
        with self._lock:
            record = self._records.get(trace_id)
            if record is None:
                return
            record["status"] = status
            record["finished_at"] = datetime.now(timezone.utc).isoformat()
            record["total_duration_ms"] = round(
                (time.monotonic() - record["started_monotonic"]) * 1000, 1
            )

    def fail_for_user(self, trace_id: Optional[str], *, user_id: str) -> None:
        """Mark an owned preflight trace failed without exposing foreign traces."""
        if not trace_id:
            return
        with self._lock:
            record = self._records.get(trace_id)
            if record is None or record["user_id"] != user_id:
                return
            if record["status"] in {"queued", "running"}:
                record["status"] = "failed"
                record["finished_at"] = datetime.now(timezone.utc).isoformat()
                record["total_duration_ms"] = round(
                    (time.monotonic() - record["started_monotonic"]) * 1000, 1
                )

    def get_for_user(self, trace_id: str, *, user_id: str) -> Dict[str, Any]:
        with self._lock:
            self._prune_locked()
            record = self._records.get(trace_id)
            if record is None or record["user_id"] != user_id:
                raise KeyError("trace_not_found")
            return self._public(record)

    @staticmethod
    def _public(record: Dict[str, Any]) -> Dict[str, Any]:
        snapshot = deepcopy(record)
        snapshot.pop("user_id", None)
        started_monotonic = snapshot.pop("started_monotonic")
        for event in snapshot["nodes"]:
            event.pop("started_monotonic", None)
        if snapshot["total_duration_ms"] is None:
            snapshot["total_duration_ms"] = round(
                (time.monotonic() - started_monotonic) * 1000, 1
            )
        return snapshot


execution_trace_store = ExecutionTraceStore()


@contextmanager
def trace_context(trace_id: str) -> Iterator[None]:
    token = _active_trace_id.set(trace_id)
    try:
        yield
    finally:
        _active_trace_id.reset(token)


def _node_metadata(result: Any) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    metadata: Dict[str, Any] = {}
    for key in (
        "selected_agent",
        "next_route",
        "has_image",
        "image_type",
        "decision_confidence",
        "retrieval_confidence",
        "needs_human_validation",
    ):
        value = result.get(key)
        if value is not None:
            metadata[key] = value
    return metadata


def traced_node(node_id: str, operation: Callable[..., T]) -> Callable[..., T]:
    """Wrap a graph node so polling clients can observe its live status."""
    @wraps(operation)
    def wrapper(*args, **kwargs):
        state = args[0] if args and hasattr(args[0], "get") else {}
        trace_id = _active_trace_id.get() or state.get("execution_trace_id")
        event_id = execution_trace_store.start_node(trace_id, node_id) if trace_id else None
        try:
            result = operation(*args, **kwargs)
        except BaseException as exc:
            if trace_id:
                execution_trace_store.finish_node(
                    trace_id,
                    event_id,
                    status="failed",
                    metadata={"error_type": type(exc).__name__},
                )
            raise
        if trace_id:
            execution_trace_store.finish_node(
                trace_id,
                event_id,
                status="completed",
                metadata=_node_metadata(result),
            )
        return result
    return wrapper

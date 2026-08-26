"""Request-scoped RAG data that must not be persisted in LangGraph state."""

from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Dict, List


@dataclass
class RAGRequestContext:
    original_query: str
    query: str
    chat_history: str = ""
    retrieved_documents: List[Dict[str, Any]] = field(default_factory=list)
    reranked_documents: List[Dict[str, Any]] = field(default_factory=list)
    picture_paths: List[str] = field(default_factory=list)
    fallback_response: str = ""


class RAGRequestContextStore:
    """Thread-safe ephemeral storage keyed by the private execution trace id."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._contexts: Dict[str, RAGRequestContext] = {}

    def create(self, trace_id: str, context: RAGRequestContext) -> None:
        with self._lock:
            self._contexts[trace_id] = context

    def get(self, trace_id: str) -> RAGRequestContext:
        with self._lock:
            try:
                return self._contexts[trace_id]
            except KeyError as exc:
                raise RuntimeError("RAG request context is unavailable") from exc

    def discard(self, trace_id: str) -> None:
        with self._lock:
            self._contexts.pop(trace_id, None)


rag_request_context_store = RAGRequestContextStore()

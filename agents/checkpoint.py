"""LangGraph checkpoint factory.

PostgreSQL is used when CHECKPOINT_DATABASE_URL is configured.  The memory
fallback is intentionally explicit for local development and test runs.
"""

import logging
import os
from contextlib import ExitStack

from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)
_stack = ExitStack()
_checkpointer = None


class ConversationMemorySaver(MemorySaver):
    """Keep the latest completed state rather than every historical snapshot."""

    def prune_thread(self, thread_id: str) -> None:
        # Called only after graph execution and message trimming, while the
        # caller holds the conversation lock. No graph tasks remain pending.
        namespaces = self.storage.get(thread_id, {})
        for checkpoints in namespaces.values():
            if checkpoints:
                latest = max(checkpoints)
                state, metadata, _parent = checkpoints[latest]
                checkpoints.clear()
                checkpoints[latest] = (state, metadata, None)
        for key in list(self.writes):
            if key[0] == thread_id:
                del self.writes[key]

    def delete_thread(self, thread_id: str) -> None:
        self.storage.pop(thread_id, None)
        for key in list(self.writes):
            if key[0] == thread_id:
                del self.writes[key]


def delete_conversation_checkpoint(thread_id: str) -> None:
    if _checkpointer is None and not os.getenv("CHECKPOINT_DATABASE_URL", "").strip():
        return
    saver = get_checkpointer()
    delete = getattr(saver, "delete_thread", None)
    if delete is not None:
        try:
            delete(thread_id)
            return
        except NotImplementedError:
            pass  # Older PostgreSQL adapters may inherit an unimplemented API.
    # langgraph-checkpoint-postgres 2.x predates delete_thread. Its cursor
    # context serializes access to the connection shared by the saver.
    with saver._cursor() as cursor:
        cursor.execute("DELETE FROM checkpoint_writes WHERE thread_id = %s", (thread_id,))
        cursor.execute("DELETE FROM checkpoint_blobs WHERE thread_id = %s", (thread_id,))
        cursor.execute("DELETE FROM checkpoints WHERE thread_id = %s", (thread_id,))


def get_checkpointer():
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer
    database_url = os.getenv("CHECKPOINT_DATABASE_URL", "").strip()
    if not database_url:
        logger.warning("CHECKPOINT_DATABASE_URL is not set; using in-memory checkpoints")
        _checkpointer = ConversationMemorySaver()
        return _checkpointer
    try:
        from langgraph.checkpoint.postgres import PostgresSaver

        _checkpointer = _stack.enter_context(PostgresSaver.from_conn_string(database_url))
        _checkpointer.setup()
        logger.info("Using PostgreSQL LangGraph checkpoint store")
    except Exception:
        logger.exception("PostgreSQL checkpoint setup failed; refusing to silently share state")
        raise
    return _checkpointer


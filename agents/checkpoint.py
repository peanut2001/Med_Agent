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


def get_checkpointer():
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer
    database_url = os.getenv("CHECKPOINT_DATABASE_URL", "").strip()
    if not database_url:
        logger.warning("CHECKPOINT_DATABASE_URL is not set; using in-memory checkpoints")
        _checkpointer = MemorySaver()
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


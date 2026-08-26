"""Process-local concurrency controls for the single-container deployment."""

from contextlib import contextmanager
from collections import deque
import os
from threading import BoundedSemaphore, Event, RLock
from typing import Callable, Deque, Dict, Iterator, TypeVar
from dotenv import load_dotenv


load_dotenv()


T = TypeVar("T")


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


class KeyedLockPool:
    """Serialize work per key and discard unused locks after each request."""

    def __init__(self) -> None:
        self._guard = RLock()
        self._queues: Dict[str, Deque[Event]] = {}

    @contextmanager
    def hold(self, key: str) -> Iterator[None]:
        waiter = Event()
        with self._guard:
            queue = self._queues.setdefault(key, deque())
            queue.append(waiter)
            if len(queue) == 1:
                waiter.set()
        waiter.wait()
        try:
            yield
        finally:
            with self._guard:
                queue = self._queues[key]
                current = queue.popleft()
                if current is not waiter:
                    raise RuntimeError("conversation lock queue is corrupted")
                if queue:
                    queue[0].set()
                else:
                    self._queues.pop(key, None)

    @property
    def active_key_count(self) -> int:
        with self._guard:
            return len(self._queues)


agent_request_slots = BoundedSemaphore(
    _positive_int("MAX_CONCURRENT_AGENT_REQUESTS", 4)
)
image_inference_slots = BoundedSemaphore(
    _positive_int("MAX_CONCURRENT_IMAGE_INFERENCES", 1)
)
conversation_locks = KeyedLockPool()


def run_agent_request(key: str, operation: Callable[..., T], *args, **kwargs) -> T:
    with conversation_locks.hold(key):
        with agent_request_slots:
            return operation(*args, **kwargs)


def run_image_inference(operation: Callable[..., T], *args, **kwargs) -> T:
    with image_inference_slots:
        return operation(*args, **kwargs)

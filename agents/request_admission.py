"""Bound expensive HTTP work before it can occupy the shared worker pool."""

import asyncio
from dataclasses import dataclass
from weakref import WeakKeyDictionary

import anyio
from starlette.responses import JSONResponse


@dataclass
class _QueueState:
    slots: asyncio.Semaphore
    capacity: int
    admitted: int = 0


class RequestAdmissionMiddleware:
    def __init__(self, app, *, max_active: int, max_queued: int, wait_seconds: float):
        self.app = app
        self.max_active = max_active
        self.max_queued = max_queued
        self.wait_seconds = wait_seconds
        # Test clients may run the same app on different event loops.
        self._states = WeakKeyDictionary()

    async def __call__(self, scope, receive, send):
        method, path = scope.get("method"), scope.get("path", "")
        expensive = (
            method == "POST" and path in {"/chat", "/upload", "/validate", "/transcribe", "/generate-speech"}
        ) or (method == "DELETE" and path.startswith("/conversations/"))
        if scope["type"] != "http" or not expensive:
            return await self.app(scope, receive, send)

        loop = asyncio.get_running_loop()
        state = self._states.get(loop)
        if state is None:
            workers = anyio.to_thread.current_default_thread_limiter().total_tokens
            capacity = max(1, min(self.max_active, int(workers) - 8))
            state = _QueueState(asyncio.Semaphore(capacity), capacity)
            self._states[loop] = state
        if state.admitted >= state.capacity + self.max_queued:
            return await self._reject(scope, receive, send)

        # No await between the capacity check and reservation: one event-loop
        # turn atomically reserves a bounded place in the asynchronous queue.
        state.admitted += 1
        acquired = False
        try:
            try:
                await asyncio.wait_for(state.slots.acquire(), timeout=self.wait_seconds)
                acquired = True
            except TimeoutError:
                return await self._reject(scope, receive, send)
            await self.app(scope, receive, send)
        finally:
            if acquired:
                state.slots.release()
            state.admitted -= 1

    @staticmethod
    async def _reject(scope, receive, send):
        response = JSONResponse(
            status_code=429,
            content={"detail": "服务繁忙，请稍后重试。"},
            headers={"Retry-After": "2"},
        )
        await response(scope, receive, send)

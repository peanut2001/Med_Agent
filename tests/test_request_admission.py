import asyncio
from threading import Event

import anyio
import httpx
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from agents.request_admission import RequestAdmissionMiddleware


def test_queued_chat_does_not_block_health_login_or_cancellation():
    async def exercise():
        limiter = anyio.to_thread.current_default_thread_limiter()
        original = limiter.total_tokens
        limiter.total_tokens = 4
        release = Event()
        entered = asyncio.Event()
        api = FastAPI()

        @api.post("/chat")
        async def chat():
            entered.set()
            await run_in_threadpool(release.wait, 5)
            return {"ok": True}

        @api.get("/health")
        def health():
            return {"ok": True}

        @api.post("/auth/login")
        def login():
            return {"ok": True}

        @api.post("/traces/test/cancel")
        def cancel():
            return {"ok": True}

        middleware = RequestAdmissionMiddleware(api, max_active=4, max_queued=8, wait_seconds=2)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=middleware), base_url="http://test") as client:
            tasks = [asyncio.create_task(client.post("/chat")) for _ in range(5)]
            try:
                await asyncio.wait_for(entered.wait(), 1)
                for method, route in [("GET", "/health"), ("POST", "/auth/login"), ("POST", "/traces/test/cancel")]:
                    response = await asyncio.wait_for(client.request(method, route), 1)
                    assert response.status_code == 200
                assert limiter.borrowed_tokens <= 1
            finally:
                release.set()
                await asyncio.gather(*tasks)
                limiter.total_tokens = original
            assert all(task.result().status_code == 200 for task in tasks)
            assert middleware._states[asyncio.get_running_loop()].admitted == 0

    asyncio.run(exercise())


def test_queue_overflow_and_timeout_return_429_and_reclaim_capacity():
    async def exercise():
        release, entered = asyncio.Event(), asyncio.Event()
        api = FastAPI()

        @api.post("/chat")
        async def chat():
            entered.set()
            await release.wait()
            return {"ok": True}

        middleware = RequestAdmissionMiddleware(api, max_active=1, max_queued=1, wait_seconds=.05)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=middleware), base_url="http://test") as client:
            active = asyncio.create_task(client.post("/chat"))
            await entered.wait()
            queued = asyncio.create_task(client.post("/chat"))
            await asyncio.sleep(0)
            overflow = await client.post("/chat")
            assert overflow.status_code == 429
            assert overflow.headers["retry-after"] == "2"
            assert (await queued).status_code == 429
            release.set()
            assert (await active).status_code == 200
            assert (await client.post("/chat")).status_code == 200
            assert middleware._states[asyncio.get_running_loop()].admitted == 0

    asyncio.run(exercise())


def test_cancelled_waiter_and_failed_handler_release_queue_places():
    async def exercise():
        release, entered = asyncio.Event(), asyncio.Event()
        api = FastAPI()

        @api.post("/chat")
        async def chat():
            entered.set()
            await release.wait()
            raise RuntimeError("simulated failure")

        middleware = RequestAdmissionMiddleware(api, max_active=1, max_queued=1, wait_seconds=1)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=middleware, raise_app_exceptions=False), base_url="http://test") as client:
            active = asyncio.create_task(client.post("/chat"))
            await entered.wait()
            queued = asyncio.create_task(client.post("/chat"))
            await asyncio.sleep(0)
            queued.cancel()
            try:
                await queued
            except asyncio.CancelledError:
                pass
            release.set()
            assert (await active).status_code == 500
            assert middleware._states[asyncio.get_running_loop()].admitted == 0
            assert (await client.post("/chat")).status_code == 500

    asyncio.run(exercise())

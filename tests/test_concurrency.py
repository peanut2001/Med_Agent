from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Event, Lock
import time

import agents.concurrency as concurrency


def test_same_conversation_is_serialized_and_lock_is_reclaimed(monkeypatch):
    monkeypatch.setattr(concurrency, "conversation_locks", concurrency.KeyedLockPool())
    monkeypatch.setattr(concurrency, "agent_request_slots", BoundedSemaphore(4))
    active = 0
    maximum = 0
    order = []
    guard = Lock()
    first_entered = Event()

    def work(name):
        nonlocal active, maximum
        with guard:
            active += 1
            maximum = max(maximum, active)
            order.append(name)
        if name == "first":
            first_entered.set()
        time.sleep(0.04)
        with guard:
            active -= 1

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(concurrency.run_agent_request, "u:c", work, "first")
        assert first_entered.wait(timeout=1)
        second = executor.submit(concurrency.run_agent_request, "u:c", work, "second")
        first.result(timeout=1)
        second.result(timeout=1)

    assert maximum == 1
    assert order == ["first", "second"]
    assert concurrency.conversation_locks.active_key_count == 0


def test_different_conversations_overlap_but_respect_global_limit(monkeypatch):
    monkeypatch.setattr(concurrency, "conversation_locks", concurrency.KeyedLockPool())
    monkeypatch.setattr(concurrency, "agent_request_slots", BoundedSemaphore(2))
    active = 0
    maximum = 0
    guard = Lock()

    def work():
        nonlocal active, maximum
        with guard:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.04)
        with guard:
            active -= 1

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [
            executor.submit(concurrency.run_agent_request, f"u:c{i}", work)
            for i in range(6)
        ]
        for future in futures:
            future.result(timeout=2)

    assert maximum == 2
    assert concurrency.conversation_locks.active_key_count == 0


def test_image_inference_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(concurrency, "image_inference_slots", BoundedSemaphore(1))
    active = 0
    maximum = 0
    guard = Lock()

    def infer():
        nonlocal active, maximum
        with guard:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.03)
        with guard:
            active -= 1

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(concurrency.run_image_inference, infer) for _ in range(3)]
        for future in futures:
            future.result(timeout=1)

    assert maximum == 1


from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

import agents.artifacts as artifacts
from agents.validation_store import ValidationStore


def test_artifact_paths_are_unique_and_confined(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "PRIVATE_ARTIFACT_ROOT", tmp_path.resolve())
    first = artifacts.create_private_artifact_path()
    second = artifacts.create_private_artifact_path()
    assert first != second

    first.write_bytes(b"first")
    second.write_bytes(b"second")
    assert artifacts.resolve_private_artifact(str(first)) == first

    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(b"private")
    with pytest.raises(FileNotFoundError):
        artifacts.resolve_private_artifact(str(outside))


def test_cleanup_removes_only_expired_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "PRIVATE_ARTIFACT_ROOT", tmp_path.resolve())
    old = artifacts.create_private_artifact_path()
    fresh = artifacts.create_private_artifact_path()
    old.write_bytes(b"old")
    fresh.write_bytes(b"fresh")
    old.touch()
    fresh.touch()

    now = fresh.stat().st_mtime
    old_time = now - 100
    import os
    os.utime(old, (old_time, old_time))

    assert artifacts.cleanup_expired_artifacts(50, now=now) == 1
    assert not old.exists()
    assert fresh.exists()


def test_concurrent_producers_get_distinct_correct_files(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "PRIVATE_ARTIFACT_ROOT", tmp_path.resolve())

    def produce(payload: bytes):
        def writer(path: str) -> bool:
            Path(path).write_bytes(payload)
            return True
        return artifacts.produce_private_artifact(writer)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(produce, b"first-image")
        second_future = executor.submit(produce, b"second-image")
        first = first_future.result(timeout=1)
        second = second_future.result(timeout=1)

    assert first is not None and second is not None and first != second
    assert {first.read_bytes(), second.read_bytes()} == {b"first-image", b"second-image"}


def test_validation_artifact_lookup_hides_foreign_records(tmp_path):
    store = ValidationStore()
    record = store.create(
        user_id="user-a",
        conversation_id="conversation-a",
        thread_id="user-a:conversation-a",
        agent_name="SKIN_LESION_AGENT",
        original_output="result",
        result_image_path=str(Path(tmp_path) / "result.png"),
    )

    assert store.get_for_user(record.validation_id, user_id="user-a") == record
    with pytest.raises(KeyError):
        store.get_for_user(record.validation_id, user_id="user-b")

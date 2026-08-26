"""Private, server-side artifact paths and retention cleanup."""

import os
from pathlib import Path
import time
import uuid
from typing import Callable
from dotenv import load_dotenv


load_dotenv()


PRIVATE_ARTIFACT_ROOT = Path(
    os.getenv("PRIVATE_ARTIFACT_ROOT", "uploads/private_results")
).resolve()


def create_private_artifact_path(suffix: str = ".png") -> Path:
    PRIVATE_ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    normalized_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return PRIVATE_ARTIFACT_ROOT / f"{uuid.uuid4().hex}{normalized_suffix}"


def produce_private_artifact(
    producer: Callable[[str], bool], suffix: str = ".png"
) -> Path | None:
    """Give a producer a unique path and remove incomplete/failed output."""
    path = create_private_artifact_path(suffix)
    try:
        produced = producer(str(path))
        if not produced or not path.is_file():
            path.unlink(missing_ok=True)
            return None
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise


def resolve_private_artifact(path_value: str) -> Path:
    """Resolve a stored path and reject anything outside the private root."""
    path = Path(path_value).resolve()
    try:
        path.relative_to(PRIVATE_ARTIFACT_ROOT)
    except ValueError as exc:
        raise FileNotFoundError("artifact_not_found") from exc
    if not path.is_file():
        raise FileNotFoundError("artifact_not_found")
    return path


def cleanup_expired_artifacts(ttl_seconds: int, *, now: float | None = None) -> int:
    """Remove only regular artifact files older than the configured TTL."""
    if ttl_seconds <= 0 or not PRIVATE_ARTIFACT_ROOT.exists():
        return 0
    cutoff = (time.time() if now is None else now) - ttl_seconds
    removed = 0
    for path in PRIVATE_ARTIFACT_ROOT.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except FileNotFoundError:
            continue
    return removed

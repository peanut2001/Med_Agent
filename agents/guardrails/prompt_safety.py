"""Utilities for keeping untrusted text separate from model instructions."""

import re
from typing import Optional


DEFAULT_MAX_CHARS = 12_000


def sanitize_untrusted_text(value: object, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Normalize and cap user/retrieved/web text before putting it in a prompt."""
    text = "" if value is None else str(value)
    text = text.replace("\x00", "")
    # Keep prompts readable and prevent control characters from changing the
    # transport format. Newlines and tabs are intentionally preserved.
    text = "".join(ch for ch in text if ch in "\n\r\t" or ord(ch) >= 32)
    return text[:max_chars]


def untrusted_block(label: str, value: object, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Return a visibly delimited block that models must treat as data."""
    safe_label = re.sub(r"[^A-Za-z0-9_-]+", "_", label)
    text = sanitize_untrusted_text(value, max_chars=max_chars)
    return (
        f"<untrusted-data source=\"{safe_label}\">\n"
        f"{text}\n"
        f"</untrusted-data>"
    )


_SECRET_PATTERNS = (
    re.compile(r"(?i)(openai|tavily|huggingface|eleven[_ -]?labs|qdrant)[_-]?(api[_ -]?key|token)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)(password|passwd|secret|api[_ -]?key|access[_ -]?token)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]+?-----END [A-Z ]+ PRIVATE KEY-----"),
)


def redact_sensitive_output(value: Optional[str]) -> str:
    """Remove common credential forms from text before it reaches a user/log."""
    text = sanitize_untrusted_text(value or "")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


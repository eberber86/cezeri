"""Append-only JSONL audit log with API-key redaction.

Per CONTRACT.md "Audit": the runtime logs server start/stop, every tool call
(name + redacted args), every approval proposed/decided, every file read/write,
and every LLM call (provider+model only). Entries live at
``<data-dir>/audit.jsonl`` and are read back via :func:`read`.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

from .config import data_dir

AUDIT_FILENAME = "audit.jsonl"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# Anything that looks like a secret value gets scrubbed before it is logged.
_KEY_VALUE_RE = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|bearer)\b\s*[:=]\s*['\"]?([^'\"\s,}]+)"
)
_TOKEN_RES = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"),      # Anthropic
    re.compile(r"\bsk-(?!ant-)[A-Za-z0-9]{16,}\b"),  # OpenAI-style
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),   # Slack-style
    re.compile(r"\bghp_[A-Za-z0-9]{16,}\b"),        # GitHub-style
]


def redact(value):
    """Recursively redact anything resembling an API key."""
    if isinstance(value, str):
        value = _KEY_VALUE_RE.sub(lambda m: f"{m.group(1)}=***REDACTED***", value)
        for rx in _TOKEN_RES:
            value = rx.sub("***REDACTED***", value)
        return value
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def _audit_path() -> str:
    path = os.path.join(data_dir(), AUDIT_FILENAME)
    if not os.path.exists(path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
        os.close(fd)
    else:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return path


def log(actor: str, action: str, detail: str = "", plan_id: str | None = None) -> dict:
    """Append one audit entry (JSONL). Secrets in ``detail`` are redacted."""
    entry = {
        "ts": _utc_now(),
        "actor": actor,
        "action": action,
        "detail": redact(detail),
        "plan_id": plan_id,
    }
    line = json.dumps(entry, ensure_ascii=False)
    with open(_audit_path(), "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return entry


def read(limit: int = 200) -> list[dict]:
    """Return the most recent ``limit`` audit entries (oldest first)."""
    path = os.path.join(data_dir(), AUDIT_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return []
    entries: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries[-limit:] if limit and limit > 0 else entries

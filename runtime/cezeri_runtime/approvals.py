"""Permission-gate store for file writes and code execution.

Per CONTRACT.md "Scoped files": writes NEVER happen directly. The agent calls
``propose_write``/``propose_exec`` (in ``tools/files.py``), an approval is
created here, the step pauses as ``awaiting_approval``, and only on approval
does the runtime perform the write (``file_write``) — code execution stays
stubbed in Phase 1 (approval + audit only, per contract non-goals).

Store: JSON list at ``<data-dir>/approvals.json``.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from .audit import log
from .config import data_dir

APPROVALS_FILENAME = "approvals.json"

KINDS = ("file_write", "code_exec")
STATUSES = ("pending", "approved", "denied")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _store_path() -> str:
    path = os.path.join(data_dir(), APPROVALS_FILENAME)
    if not os.path.exists(path):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump([], fh)
            fh.write("\n")
        os.replace(tmp, path)
    return path


def _load() -> list[dict]:
    _store_path()
    try:
        with open(_store_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save(entries: list[dict]) -> None:
    path = _store_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def create(
    kind: str,
    plan_id: str | None,
    step_id: str | None,
    summary: str,
    payload_preview: str,
    payload: dict,
    actor: str = "system",
) -> dict:
    """Create a pending approval and return it."""
    if kind not in KINDS:
        raise ValueError(f"unknown approval kind: {kind!r} (expected one of {KINDS})")
    entry = {
        "id": "ap_" + uuid.uuid4().hex[:8],
        "plan_id": plan_id,
        "step_id": step_id,
        "kind": kind,
        "summary": summary,
        "payload_preview": str(payload_preview)[:2000],
        "payload": payload or {},
        "status": "pending",
        "created_at": _utc_now(),
        "decided_at": None,
        "decision_note": None,
    }
    entries = _load()
    entries.append(entry)
    _save(entries)
    log(actor, "approval_proposed",
        f"{kind} {entry['id']}: {summary}", plan_id=plan_id)
    return entry


def get(approval_id: str) -> dict:
    """Return one approval by id, else raise KeyError."""
    for entry in _load():
        if entry.get("id") == approval_id:
            return entry
    raise KeyError(f"unknown approval id: {approval_id!r}")


def list_pending() -> list[dict]:
    """All approvals still awaiting a decision."""
    return [e for e in _load() if e.get("status") == "pending"]


def list_all() -> list[dict]:
    return _load()


def decide(approval_id: str, approved: bool, note: str = "", actor: str = "user") -> dict:
    """Decide an approval. On approving ``file_write``, performs the write
    via the scoped writer in ``tools/files.py`` and audits it. ``code_exec``
    is stubbed in Phase 1: approval + audit only, no actual execution."""
    entries = _load()
    entry = next((e for e in entries if e.get("id") == approval_id), None)
    if entry is None:
        raise KeyError(f"unknown approval id: {approval_id!r}")
    if entry.get("status") != "pending":
        raise ValueError(f"approval {approval_id} already decided "
                         f"(status={entry.get('status')})")

    entry["status"] = "approved" if approved else "denied"
    entry["decided_at"] = _utc_now()
    entry["decision_note"] = note or ""

    if approved and entry["kind"] == "file_write":
        # Lazy import: tools/files.py imports this module at top level.
        from .tools.files import perform_write
        payload = entry.get("payload") or {}
        path = payload.get("path")
        content = payload.get("content", "")
        if not path:
            entry["status"] = "denied"
            entry["decision_note"] = (note + " | write skipped: no path in payload").strip(" |")
            detail = f"{entry['id']}: approved but payload had no path; write skipped"
        else:
            perform_write(path, content, actor=actor, plan_id=entry.get("plan_id"))
            detail = f"{entry['id']}: approved — wrote {path} ({len(content)} chars)"
    elif approved and entry["kind"] == "code_exec":
        # Phase 1 non-goal: no actual code execution.
        detail = (f"{entry['id']}: code_exec approved — execution stubbed in "
                  f"Phase 1 (approval + audit only, nothing ran)")
    else:
        detail = f"{entry['id']}: {entry['status']} — {entry['kind']}"

    _save(entries)
    log(actor, "approval_decided", detail, plan_id=entry.get("plan_id"))
    return entry

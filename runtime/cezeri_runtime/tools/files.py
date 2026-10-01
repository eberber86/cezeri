"""Scoped file tools for the Cezeri agents.

Per CONTRACT.md "Scoped files":
- Every path is resolved to absolute and MUST be inside an approved dir,
  else ``PermissionError`` is raised AND the denial is audited.
- ``read_file`` / ``list_dir`` execute immediately (reads are safe).
- ``propose_write`` / ``propose_exec`` create an approval via
  ``approvals.py`` and return ``{"status": "awaiting_approval", ...}`` —
  the actual write happens only in ``approvals.decide()`` on approval.
  Code execution stays stubbed (approval + audit only, per contract
  non-goals).
"""

from __future__ import annotations

import os

from .. import approvals
from ..audit import log
from ..config import get_approved_dirs


def resolve_scoped(path: str, actor: str = "system") -> str:
    """Resolve ``path`` to an absolute path inside an approved dir.

    Raises PermissionError (and audits the denial) if the resolved path is
    not contained in any approved directory.
    """
    resolved = os.path.realpath(os.path.expanduser(path))
    for approved in get_approved_dirs():
        base = os.path.realpath(approved)
        if resolved == base or resolved.startswith(base + os.sep):
            return resolved
    log(actor, "permission_denied",
        f"path outside approved dirs: {path!r} (resolved: {resolved!r})")
    raise PermissionError(
        f"Path is not inside an approved directory: {path!r}. "
        "Ask the user to approve the folder in Settings first."
    )


def read_file(path: str, actor: str = "system", plan_id: str | None = None) -> str:
    """Read a text file inside an approved dir. Executes immediately."""
    resolved = resolve_scoped(path, actor=actor)
    try:
        with open(resolved, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except FileNotFoundError:
        log(actor, "tool_call", f"read_file({path!r}) -> FileNotFoundError",
            plan_id=plan_id)
        raise
    except IsADirectoryError:
        log(actor, "tool_call", f"read_file({path!r}) -> IsADirectoryError",
            plan_id=plan_id)
        raise
    log(actor, "tool_call",
        f"read_file({path!r}) -> {len(content)} chars", plan_id=plan_id)
    return content


def list_dir(path: str, actor: str = "system", plan_id: str | None = None) -> list[dict]:
    """List a directory inside an approved dir. Executes immediately."""
    resolved = resolve_scoped(path, actor=actor)
    try:
        names = sorted(os.listdir(resolved))
    except FileNotFoundError:
        log(actor, "tool_call", f"list_dir({path!r}) -> FileNotFoundError",
            plan_id=plan_id)
        raise
    entries: list[dict] = []
    for name in names:
        full = os.path.join(resolved, name)
        is_dir = os.path.isdir(full)
        entries.append({
            "name": name,
            "type": "dir" if is_dir else "file",
            "size": 0 if is_dir else os.path.getsize(full),
        })
    entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
    log(actor, "tool_call",
        f"list_dir({path!r}) -> {len(entries)} entries", plan_id=plan_id)
    return entries


def propose_write(
    path: str,
    content: str,
    plan_id: str | None = None,
    step_id: str | None = None,
    actor: str = "system",
) -> dict:
    """Propose a file write. Creates an approval and pauses the step.

    The write itself happens only if the approval is granted (see
    ``approvals.decide``). Returns a dict telling the agent the step is now
    ``awaiting_approval``.
    """
    resolved = resolve_scoped(path, actor=actor)  # raises before any approval
    content = "" if content is None else str(content)
    line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    approval = approvals.create(
        kind="file_write",
        plan_id=plan_id,
        step_id=step_id,
        summary=f"Write {resolved} ({line_count} lines, {len(content)} chars)",
        payload_preview=content[:500],
        payload={"path": resolved, "content": content},
        actor=actor,
    )
    return {
        "status": "awaiting_approval",
        "approval_id": approval["id"],
        "kind": "file_write",
        "message": (
            f"Write to {resolved} is awaiting approval "
            f"(approval id: {approval['id']}). The step is paused until "
            "the user approves or denies it."
        ),
    }


def propose_exec(
    description: str,
    code_hint: str = "",
    plan_id: str | None = None,
    step_id: str | None = None,
    actor: str = "system",
) -> dict:
    """Propose running code. Creates an approval and pauses the step.

    Phase 1: execution itself is stubbed — approval + audit only, no actual
    code runs even if approved (per contract non-goals).
    """
    approval = approvals.create(
        kind="code_exec",
        plan_id=plan_id,
        step_id=step_id,
        summary=f"Execute code: {description}",
        payload_preview=str(code_hint)[:500],
        payload={"description": description, "code_hint": code_hint},
        actor=actor,
    )
    return {
        "status": "awaiting_approval",
        "approval_id": approval["id"],
        "kind": "code_exec",
        "message": (
            f"Code execution is awaiting approval (approval id: "
            f"{approval['id']}). The step is paused until the user approves "
            "or denies it. Note: code execution is stubbed in Phase 1 — "
            "approval only records the decision."
        ),
    }


def perform_write(
    path: str,
    content: str,
    actor: str = "system",
    plan_id: str | None = None,
) -> str:
    """Actually write a file (internal). Called only by ``approvals.decide``
    after approval. Scope is re-verified here (defense in depth)."""
    resolved = resolve_scoped(path, actor=actor)
    parent = os.path.dirname(resolved)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(resolved, "w", encoding="utf-8") as fh:
        fh.write(content)
    log(actor, "file_write",
        f"wrote {resolved} ({len(content)} chars) after approval",
        plan_id=plan_id)
    return resolved

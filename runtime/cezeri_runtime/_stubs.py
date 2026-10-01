"""Internal fallbacks for sibling W3/W4 modules.

`config.py`, `approvals.py` and `audit.py` are built by other workers to the
same contract. Every helper here first tries the real module (when it exists
and exposes the expected attribute) and otherwise falls back to a minimal
local implementation, so this worker's code is importable and runnable
standalone. Integration simply replaces the fallbacks.

Security note: nothing here ever writes the API key to logs or audit —
callers must pass only redacted details to `audit_log`.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------- data dir

def data_dir() -> Path:
    """Runtime data dir: %APPDATA%/Cezeri on Windows, ~/.cezeri elsewhere."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        d = Path(base) / "Cezeri"
    else:
        d = Path.home() / ".cezeri"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _real_module(name: str):
    try:
        mod = __import__(f"cezeri_runtime.{name}", fromlist=["*"])
        return mod
    except ImportError:
        return None


# ------------------------------------------------------------------ config

_CONFIG_FILE = "config.json"


def _file_config() -> dict:
    p = data_dir() / _CONFIG_FILE
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except Exception:
        return {}


def get_provider() -> str:
    m = _real_module("config")
    if m is not None and hasattr(m, "get_provider"):
        return m.get_provider()
    return (
        os.environ.get("CEZERI_PROVIDER")
        or _file_config().get("provider")
        or "anthropic"
    )


def get_model() -> str:
    m = _real_module("config")
    if m is not None and hasattr(m, "get_model"):
        return m.get_model()
    return os.environ.get("CEZERI_MODEL") or _file_config().get("model") or "claude-sonnet-4-5"


def key_file_path() -> Path:
    return data_dir() / "api_key"


def get_api_key() -> str | None:
    m = _real_module("config")
    if m is not None and hasattr(m, "get_api_key"):
        return m.get_api_key()
    env = os.environ.get("CEZERI_API_KEY")
    if env:
        return env
    kf = key_file_path()
    try:
        if kf.exists():
            return kf.read_text().strip() or None
    except Exception:
        pass
    return None


def has_key() -> bool:
    m = _real_module("config")
    if m is not None and hasattr(m, "has_key"):
        return bool(m.has_key())
    return bool(get_api_key())


def save_api_key(key: str) -> None:
    m = _real_module("config")
    if m is not None and hasattr(m, "save_api_key"):
        m.save_api_key(key)
        return
    kf = key_file_path()
    kf.write_text(key.strip() + "\n")
    try:
        os.chmod(kf, 0o600)
    except Exception:
        pass


def get_approved_dirs() -> list[str]:
    m = _real_module("config")
    if m is not None and hasattr(m, "get_approved_dirs"):
        return list(m.get_approved_dirs())
    env = os.environ.get("CEZERI_APPROVED_DIRS")
    if env:
        return [d for d in env.split(os.pathsep) if d]
    return list(_file_config().get("approved_dirs") or [])


def update_config(
    provider: str | None = None,
    model: str | None = None,
    approved_dirs: list[str] | None = None,
) -> None:
    m = _real_module("config")
    if m is not None and hasattr(m, "update_config"):
        values: dict = {}
        if provider is not None:
            values["provider"] = provider
        if model is not None:
            values["model"] = model
        if approved_dirs is not None:
            values["approved_dirs"] = list(approved_dirs)
        try:
            m.update_config(values)  # sibling W4 signature: update_config(dict)
            return
        except TypeError:
            # Fall back to a keyword-argument form if a variant exists.
            try:
                m.update_config(provider=provider, model=model,
                                approved_dirs=approved_dirs)
                return
            except TypeError:
                pass
    cfg = _file_config()
    if provider is not None:
        cfg["provider"] = provider
    if model is not None:
        cfg["model"] = model
    if approved_dirs is not None:
        cfg["approved_dirs"] = list(approved_dirs)
    (data_dir() / _CONFIG_FILE).write_text(json.dumps(cfg, indent=2))


# ------------------------------------------------------------------- audit

def audit_log(actor: str, action: str, detail: str, plan_id: str | None = None) -> None:
    """Append an audit entry. `detail` must already be redacted by the caller."""
    m = _real_module("audit")
    fn = getattr(m, "log", None) if m is not None else None
    if callable(fn):
        try:
            fn(actor=actor, action=action, detail=detail, plan_id=plan_id)
            return
        except Exception:
            pass
    entry = {"ts": _now_iso(), "actor": actor, "action": action,
             "detail": detail, "plan_id": plan_id}
    try:
        with (data_dir() / "audit.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def read_audit(limit: int = 200) -> list[dict]:
    m = _real_module("audit")
    fn = getattr(m, "read", None) or getattr(m, "tail", None) if m is not None else None
    if callable(fn):
        try:
            entries = fn(limit=limit)
            return list(entries)
        except Exception:
            pass
    p = data_dir() / "audit.jsonl"
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    entries = []
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(line))
        except Exception:
            continue
    return entries


# --------------------------------------------------------------- approvals

class FallbackApprovals:
    """Minimal approval store matching the contract schema (pending only)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, dict] = {}
        self._path = data_dir() / "approvals.json"
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                for ap in json.loads(self._path.read_text()):
                    self._items[ap["id"]] = ap
        except Exception:
            pass

    def _save(self) -> None:
        try:
            self._path.write_text(json.dumps(list(self._items.values()), indent=2))
        except Exception:
            pass

    def create(self, plan_id: str, step_id: str, kind: str, summary: str,
               payload_preview: str, payload: dict | None = None) -> dict:
        import uuid as _uuid
        ap = {
            "id": "ap_" + _uuid.uuid4().hex[:8],
            "plan_id": plan_id,
            "step_id": step_id,
            "kind": kind,
            "summary": summary,
            "payload_preview": (payload_preview or "")[:500],
            "payload": payload or {},
            "status": "pending",
            "created_at": _now_iso(),
        }
        with self._lock:
            self._items[ap["id"]] = ap
            self._save()
        return dict(ap)

    def get(self, approval_id: str) -> dict | None:
        with self._lock:
            ap = self._items.get(approval_id)
            return dict(ap) if ap else None

    def list(self, status: str | None = None) -> list[dict]:
        with self._lock:
            items = [dict(a) for a in self._items.values()]
        if status:
            items = [a for a in items if a["status"] == status]
        return items

    def decide(self, approval_id: str, approved: bool, note: str = "") -> dict | None:
        with self._lock:
            ap = self._items.get(approval_id)
            if not ap:
                return None
            ap["status"] = "approved" if approved else "denied"
            ap["note"] = note
            ap["decided_at"] = _now_iso()
            self._save()
            return dict(ap)


_fallback_approvals: FallbackApprovals | None = None
_approvals_lock = threading.Lock()


class _ApprovalsAdapter:
    """Adapts the sibling W4 approvals module to the (create/get/list/decide)
    surface the orchestrator and server use.

    Key semantic: the W4 module performs the file write inside decide() on
    approval, so the engine must NOT write again on resume
    (`_writes_on_decide = True`).
    """

    _writes_on_decide = True

    def __init__(self, module) -> None:
        self._m = module

    def create(self, plan_id, step_id, kind, summary, payload_preview,
               payload=None) -> dict:
        return self._m.create(kind=kind, plan_id=plan_id, step_id=step_id,
                              summary=summary,
                              payload_preview=str(payload_preview or "")[:500],
                              payload=payload or {}, actor="system")

    def get(self, approval_id: str) -> dict | None:
        try:
            return self._m.get(approval_id)
        except KeyError:
            return None

    def list(self, status: str | None = None) -> list[dict]:
        if status == "pending":
            return self._m.list_pending()
        return self._m.list_all()

    def decide(self, approval_id: str, approved: bool, note: str = "") -> dict | None:
        try:
            return self._m.decide(approval_id, approved, note)
        except KeyError:
            return None


def approvals_store():
    """Sibling W4 approvals module (adapted) when present, else local fallback."""
    m = _real_module("approvals")
    if m is not None and all(hasattr(m, a) for a in ("create", "get", "decide")) \
            and (hasattr(m, "list_pending") or hasattr(m, "list")):
        return _ApprovalsAdapter(m)
    global _fallback_approvals
    with _approvals_lock:
        if _fallback_approvals is None:
            _fallback_approvals = FallbackApprovals()
        return _fallback_approvals

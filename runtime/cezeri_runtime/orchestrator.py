"""Plan/step engine for the Cezeri runtime.

Flow:
    create_plan(target, message) -> plan_id          (starts a bg thread)
      1. target == "team": the orchestrator LLM decomposes the request into
         subtasks, each assigned to one specialist by agent id.
         target == a specialist id: single step to that specialist.
      2. Each step runs a ReAct turn: llm.chat() with the specialist's
         system prompt; fenced ```tool blocks are parsed and executed via
         the tool registry (cezeri_runtime.tools.TOOLS, merged with the
         engine's built-in propose_write/propose_exec fallbacks).
      3. When a tool call creates an approval (propose_write/propose_exec),
         the step pauses as `awaiting_approval` and the plan thread blocks
         until the UI decides (server calls notify_approval_decision()).
         On approve, the engine performs the write (scoped to approved
         dirs) and audits it; code execution stays stubbed per contract.
      4. target == "team": the orchestrator assembles step results into the
         final answer (plan["final_answer"]).

Single-threaded per plan: one background thread runs the steps in order.
Step statuses: pending|running|awaiting_approval|done|failed|skipped.
Plan statuses: queued|running|awaiting_approval|done|failed.
"""

from __future__ import annotations

import inspect
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cezeri_runtime import _stubs, agents, llm

try:
    # Sibling chunk's registry (may not exist yet during parallel dev).
    from cezeri_runtime import tools as _tools_mod
    _SIBLING_TOOLS = dict(getattr(_tools_mod, "TOOLS", None) or {})
except Exception:
    _SIBLING_TOOLS = {}

MAX_REACT_ROUNDS = 8
MAX_DECOMPOSE_STEPS = 5
TOOL_RESULT_CHARS = 4000


# ------------------------------------------------------- built-in tools

def _builtin_propose_write(path: str, content: str = "", ctx: dict | None = None) -> dict:
    """Fallback propose_write used until W4's file tools land."""
    approvals = _stubs.approvals_store()
    lines = str(content).splitlines()
    ap = approvals.create(
        plan_id=(ctx or {}).get("plan_id", ""),
        step_id=(ctx or {}).get("step_id", ""),
        kind="file_write",
        summary=f"Write {path} ({len(lines)} lines)",
        payload_preview=str(content)[:500],
        payload={"path": path, "content": str(content)},
    )
    return ap


def _builtin_propose_exec(code: str = "", language: str = "python",
                          ctx: dict | None = None) -> dict:
    """Fallback propose_exec used until W4's file tools land."""
    approvals = _stubs.approvals_store()
    ap = approvals.create(
        plan_id=(ctx or {}).get("plan_id", ""),
        step_id=(ctx or {}).get("step_id", ""),
        kind="code_exec",
        summary=f"Execute {language} code ({len(str(code).splitlines())} lines) [Phase 1: stubbed]",
        payload_preview=str(code)[:500],
        payload={"code": str(code), "language": language},
    )
    return ap


# ---------------------------------------------------------------- engine

class Engine:
    def __init__(self, tools: dict | None = None) -> None:
        registry = dict(_SIBLING_TOOLS)
        if tools:
            registry.update(tools)
        # Built-in fallbacks so approvals work even before W4 registers.
        registry.setdefault("propose_write", _builtin_propose_write)
        registry.setdefault("propose_exec", _builtin_propose_exec)
        self.tools = registry
        self.plans: dict[str, dict] = {}
        self._waiters: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------- public

    def create_plan(self, target: str, message: str) -> str:
        valid = {"team", *agents.AGENT_IDS}
        if target not in valid:
            raise ValueError(f"Unknown target {target!r}. Expected one of {sorted(valid)}.")
        plan_id = "pl_" + uuid.uuid4().hex[:8]
        plan = {
            "id": plan_id,
            "title": (message or "").strip().split("\n")[0][:80] or "Untitled",
            "target": target,
            "status": "queued",
            "steps": [],
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "final_answer": None,
        }
        self.plans[plan_id] = plan
        _stubs.audit_log("user", "plan_created",
                         f"target={target} title={plan['title']!r}", plan_id=plan_id)
        t = threading.Thread(target=self._run_plan, args=(plan, message),
                             daemon=True, name=f"cezeri-{plan_id}")
        t.start()
        return plan_id

    def get_plan(self, plan_id: str) -> dict | None:
        return self.plans.get(plan_id)

    def list_plans(self) -> list[dict]:
        return [
            {"id": p["id"], "title": p["title"], "status": p["status"],
             "created_at": p["created_at"]}
            for p in self.plans.values()
        ]

    def notify_approval_decision(self, approval_id: str, approved: bool,
                                 note: str = "") -> bool:
        """Wake the plan thread blocked in _await_approval. Returns False if
        no plan is waiting on this approval."""
        with self._lock:
            waiter = self._waiters.pop(approval_id, None)
        if waiter is None:
            return False
        waiter["result"] = {"approved": approved, "note": note}
        waiter["event"].set()
        return True

    # ------------------------------------------------------------ loop

    def _run_plan(self, plan: dict, message: str) -> None:
        try:
            plan["status"] = "running"
            if plan["target"] == "team":
                specs = self._decompose(plan, message)
            else:
                specs = [{"agent": plan["target"],
                          "label": (message or "")[:80],
                          "task": message}]
            for i, spec in enumerate(specs):
                plan["steps"].append({
                    "id": f"st_{i + 1}",
                    "agent": spec["agent"],
                    "label": spec.get("label", "")[:120],
                    "status": "pending",
                    "detail": "",
                    "result": None,
                    "task": spec.get("task", ""),
                })
            for step in plan["steps"]:
                self._run_step(plan, step)
            if plan["target"] == "team":
                plan["final_answer"] = self._assemble(plan)
            else:
                plan["final_answer"] = plan["steps"][0]["result"] if plan["steps"] else None
            plan["status"] = "done"
            _stubs.audit_log("orchestrator", "plan_done",
                             f"{len(plan['steps'])} steps", plan_id=plan["id"])
        except Exception as e:  # LLMError, parse errors, etc.
            plan["status"] = "failed"
            plan["error"] = str(e)[:500]
            for step in plan["steps"]:
                if step["status"] in ("pending", "running"):
                    step["status"] = "failed"
            _stubs.audit_log("orchestrator", "plan_failed", str(e)[:300],
                             plan_id=plan["id"])

    def _decompose(self, plan: dict, message: str) -> list[dict]:
        system = agents.get_system_prompt("orchestrator")
        user = ("Decompose this request into subtasks. Respond with ONLY the "
                "JSON array.\n\nRequest: " + message)
        text = llm.chat([{"role": "system", "content": system},
                         {"role": "user", "content": user}])
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            raise llm.LLMError("Orchestrator did not return a subtask list.")
        try:
            specs = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            raise llm.LLMError(f"Orchestrator returned invalid JSON: {e}")
        if not isinstance(specs, list) or not specs:
            raise llm.LLMError("Orchestrator returned an empty subtask list.")
        valid = set(agents.AGENT_IDS)
        clean = []
        for s in specs[:MAX_DECOMPOSE_STEPS]:
            if not isinstance(s, dict) or s.get("agent") not in valid:
                continue
            clean.append({"agent": s["agent"],
                          "label": str(s.get("label", s["agent"]))[:120],
                          "task": str(s.get("task", message))})
        if not clean:
            raise llm.LLMError("Orchestrator assigned no valid specialist.")
        _stubs.audit_log("orchestrator", "plan_decomposed",
                         f"{len(clean)} steps: " +
                         ", ".join(f"{s['agent']}" for s in clean),
                         plan_id=plan["id"])
        return clean

    def _run_step(self, plan: dict, step: dict) -> None:
        step["status"] = "running"
        step["detail"] = "Working…"
        system = agents.get_system_prompt(step["agent"])
        result = self._react_turn(plan, step, system, step.get("task", ""))
        step["result"] = result
        step["status"] = "done"
        step["detail"] = (result or "")[:200]
        _stubs.audit_log(step["agent"], "step_done",
                         f"{step['id']} {step['label']!r}", plan_id=plan["id"])

    def _react_turn(self, plan: dict, step: dict, system: str, task: str) -> str:
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": task}]
        for _ in range(MAX_REACT_ROUNDS):
            text = llm.chat(messages)
            calls = llm.extract_tool_calls(text)
            if not calls:
                return self._final_text(text)
            remainder = llm.strip_tool_blocks(text)
            if remainder:
                messages.append({"role": "assistant", "content": remainder})
            for call in calls:
                result = self._execute_tool(plan, step, call["name"], call["args"])
                messages.append({"role": "user",
                                 "content": "TOOL RESULT: " +
                                 json.dumps(result, default=str)[:TOOL_RESULT_CHARS]})
        return "(Reached the tool-round limit; answer may be incomplete.)"

    @staticmethod
    def _final_text(text: str) -> str:
        body = llm.strip_tool_blocks(text)
        if "FINAL:" in body:
            return body.split("FINAL:", 1)[1].strip()
        return body

    def _assemble(self, plan: dict) -> str:
        parts = []
        for step in plan["steps"]:
            parts.append(f"[{step['agent']}] {step['label']}\n{step['result'] or ''}")
        system = agents.get_system_prompt("orchestrator")
        user = ("Assemble the specialists' completed work below into one "
                "coherent final answer. Resolve contradictions explicitly, keep "
                "all citations, and end with FINAL: + the answer.\n\n" +
                "\n\n".join(parts))
        text = llm.chat([{"role": "system", "content": system},
                         {"role": "user", "content": user}])
        return self._final_text(text)

    # ------------------------------------------------------------ tools

    def _execute_tool(self, plan: dict, step: dict, name: str, args: dict) -> dict:
        _stubs.audit_log(step["agent"], "tool_call",
                         f"{name}({_redact_args(args)})", plan_id=plan["id"])
        fn = self.tools.get(name)
        if fn is None:
            return {"error": f"unknown tool '{name}'"}
        if not isinstance(args, dict):
            return {"error": f"tool '{name}' needs an args object"}
        ctx = {"plan_id": plan["id"], "step_id": step["id"],
               "engine": self, "actor": step["agent"]}
        try:
            params = inspect.signature(fn).parameters
            kwargs = dict(args)
            # Inject plan context into whichever slots the tool declares.
            if "ctx" in params and "ctx" not in kwargs:
                kwargs["ctx"] = ctx
            for key in ("plan_id", "step_id"):
                if key in params and key not in kwargs:
                    kwargs[key] = ctx[key]
            if "actor" in params and "actor" not in kwargs:
                kwargs["actor"] = ctx["actor"]
            result = fn(**kwargs)
        except TypeError as e:
            return {"error": f"tool '{name}' argument mismatch: {e}"}
        except PermissionError as e:
            _stubs.audit_log(step["agent"], "tool_denied", f"{name}: {e}",
                             plan_id=plan["id"])
            return {"error": f"permission denied: {e}"}
        except Exception as e:
            return {"error": f"tool '{name}' failed: {e}"}
        if _is_pending_approval(result):
            return self._await_approval(plan, step, result)
        return result if isinstance(result, dict) else {"result": result}

    def _await_approval(self, plan: dict, step: dict, tool_result: dict) -> dict:
        store = _stubs.approvals_store()
        approval_id = tool_result.get("approval_id") or tool_result.get("id")
        approval = store.get(approval_id) if approval_id else None
        summary = (approval or {}).get("summary") or tool_result.get("message", "")
        step["status"] = "awaiting_approval"
        step["detail"] = summary
        plan["status"] = "awaiting_approval"
        _stubs.audit_log(step["agent"], "approval_proposed",
                         f"{(approval or {}).get('kind', '?')} {summary}",
                         plan_id=plan["id"])
        event = threading.Event()
        waiter = {"event": event, "result": None}
        with self._lock:
            self._waiters[approval_id] = waiter
        event.wait()  # released by notify_approval_decision()
        decision = waiter["result"] or {"approved": False, "note": "no decision"}
        plan["status"] = "running"
        step["status"] = "running"
        if decision["approved"]:
            outcome = self._apply_approved_action(plan, step, store, approval_id)
            return {"approved": True, **outcome}
        return {"approved": False, "note": decision.get("note", ""),
                "detail": "The user denied this action. Continue without it."}

    def _apply_approved_action(self, plan: dict, step: dict, store,
                               approval_id: str) -> dict:
        approval = store.get(approval_id) or {}
        kind = approval.get("kind")
        if getattr(store, "_writes_on_decide", False):
            # Sibling W4 approvals.decide() already performed the write /
            # recorded the stub on approval — the engine must not repeat it.
            if kind == "file_write":
                path = (approval.get("payload") or {}).get("path", "")
                return {"detail": f"Approved and wrote {path}."}
            if kind == "code_exec":
                return {"detail": "Approved, but code execution is stubbed in "
                                  "Phase 1 — not executed."}
            return {"detail": f"Approved (kind={kind})."}
        # Fallback path (no sibling approvals module): the engine performs
        # the action itself, scoped to approved dirs.
        payload = approval.get("payload") or {}
        if kind == "file_write":
            path = payload.get("path", "")
            content = payload.get("content", "")
            dest = self._scoped_path(path)  # raises PermissionError outside dirs
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
            _stubs.audit_log(step["agent"], "file_write",
                             f"{dest} ({len(str(content).splitlines())} lines)",
                             plan_id=plan["id"])
            return {"detail": f"Wrote {dest}."}
        if kind == "code_exec":
            _stubs.audit_log(step["agent"], "code_exec_stubbed",
                             "approved but not executed (Phase 1 stub)",
                             plan_id=plan["id"])
            return {"detail": "Approved, but code execution is stubbed in Phase 1 — not executed."}
        return {"detail": f"Unknown approval kind {kind!r}; nothing done."}

    @staticmethod
    def _scoped_path(path: str) -> Path:
        dest = Path(path).expanduser().resolve()
        approved = [Path(d).expanduser().resolve() for d in _stubs.get_approved_dirs()]
        if not any(dest == d or d in dest.parents for d in approved):
            raise PermissionError(
                f"{dest} is outside the approved directories "
                f"({', '.join(map(str, approved)) or 'none configured'})")
        return dest


# ------------------------------------------------------------ helpers

def _redact_args(args: dict) -> str:
    """One-line arg summary for audit: truncated, secrets masked."""
    parts = []
    for k, v in (args or {}).items():
        kl = str(k).lower()
        if any(s in kl for s in ("key", "token", "secret", "password", "auth")):
            parts.append(f"{k}=***")
        else:
            s = str(v)
            parts.append(f"{k}={s[:120] + '…' if len(s) > 120 else s}")
    return ", ".join(parts)[:400]


def _is_pending_approval(result: object) -> bool:
    """Detect a tool result that created a pending approval.

    Matches both the W4 tools' shape
    ({"status": "awaiting_approval", "approval_id": ...}) and the
    contract's approval-record shape ({"status": "pending", "id": ...}).
    """
    if not isinstance(result, dict):
        return False
    if result.get("status") == "awaiting_approval" and isinstance(result.get("approval_id"), str):
        return True
    return (result.get("status") == "pending"
            and result.get("kind") in ("file_write", "code_exec")
            and isinstance(result.get("id"), str))


_engine: Engine | None = None
_engine_lock = threading.Lock()


def get_engine() -> Engine:
    """Process-wide engine singleton (used by the HTTP server)."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = Engine()
        return _engine

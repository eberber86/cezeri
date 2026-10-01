"""Stdlib http.server-based JSON API for the Cezeri sidecar.

Endpoints (all JSON; port from CEZERI_PORT, default 8765; binds
127.0.0.1 ONLY — never 0.0.0.0):
    GET  /health                  -> {"status","version","provider"}
    POST /chat                    -> {"plan_id","status"} (frontend polls plan)
    GET  /plans                   -> {"plans":[{id,title,status,created_at}]}
    GET  /plans/{id}              -> full plan
    GET  /approvals?status=pending-> {"approvals":[...]}
    POST /approvals/{id}/decision -> {"ok":true}
    GET  /audit?limit=200         -> {"entries":[...]}
    GET  /config                  -> {"provider","model","approved_dirs","has_key"}
    PUT  /config                  -> {"ok":true}
    POST /key                     -> {"ok":true} (stores key file, mode 0600)

CORS is enabled for the Vite dev server.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from cezeri_runtime import _stubs
from cezeri_runtime.orchestrator import get_engine

VERSION = "0.1.0"
DEFAULT_PORT = 8765


class _Handler(BaseHTTPRequestHandler):
    server_version = f"CezeriSidecar/{VERSION}"

    # ------------------------------------------------------------ plumbing

    def log_message(self, fmt, *args):  # keep stderr quiet-ish
        sys.stderr.write("cezeri: " + fmt % args + "\n")

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    # ---------------------------------------------------------------- GET

    def do_GET(self) -> None:
        parts = urlparse(self.path)
        path = parts.path.rstrip("/") or "/"
        qs = parse_qs(parts.query)
        segs = [s for s in path.split("/") if s]

        if path == "/health":
            return self._send(200, {"status": "ok", "version": VERSION,
                                    "provider": _stubs.get_provider()})
        if path == "/plans":
            return self._send(200, {"plans": get_engine().list_plans()})
        if len(segs) == 2 and segs[0] == "plans":
            plan = get_engine().get_plan(segs[1])
            if plan is None:
                return self._send(404, {"error": "plan not found"})
            return self._send(200, plan)
        if path == "/approvals":
            status = (qs.get("status") or [None])[0]
            items = _stubs.approvals_store().list(status=status)
            return self._send(200, {"approvals": items})
        if path == "/audit":
            try:
                limit = int((qs.get("limit") or ["200"])[0])
            except ValueError:
                limit = 200
            return self._send(200, {"entries": _stubs.read_audit(limit)})
        if path == "/config":
            return self._send(200, {
                "provider": _stubs.get_provider(),
                "model": _stubs.get_model(),
                "approved_dirs": _stubs.get_approved_dirs(),
                "has_key": _stubs.has_key(),  # NEVER return the key itself
            })
        return self._send(404, {"error": "not found"})

    # ----------------------------------------------------------- POST/PUT

    def do_POST(self) -> None:
        segs = [s for s in (urlparse(self.path).path.rstrip("/") or "/").split("/") if s]
        body = self._read_json()

        if segs == ["chat"]:
            target = body.get("target", "team")
            message = body.get("message", "")
            try:
                plan_id = get_engine().create_plan(target, message)
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            return self._send(200, {"plan_id": plan_id, "status": "running"})

        if len(segs) == 3 and segs[0] == "approvals" and segs[2] == "decision":
            store = _stubs.approvals_store()
            ap = store.decide(segs[1], bool(body.get("approved")),
                              str(body.get("note", "")))
            if ap is None:
                return self._send(404, {"error": "approval not found"})
            get_engine().notify_approval_decision(
                segs[1], bool(body.get("approved")), str(body.get("note", "")))
            _stubs.audit_log("user", "approval_decision",
                             f"{segs[1]} -> {ap['status']}", plan_id=ap.get("plan_id"))
            return self._send(200, {"ok": True})

        if segs == ["key"]:
            key = str(body.get("api_key", "")).strip()
            if not key:
                return self._send(400, {"error": "api_key is required"})
            _stubs.save_api_key(key)
            _stubs.audit_log("user", "key_saved", "API key stored to key file")
            return self._send(200, {"ok": True})

        return self._send(404, {"error": "not found"})

    def do_PUT(self) -> None:
        segs = [s for s in (urlparse(self.path).path.rstrip("/") or "/").split("/") if s]
        if segs == ["config"]:
            body = self._read_json()
            provider = body.get("provider")
            model = body.get("model")
            approved_dirs = body.get("approved_dirs")
            if provider is not None and provider not in ("anthropic", "openai", "gemini", "kimi"):
                return self._send(400, {"error": "provider must be anthropic|openai|gemini|kimi"})
            if approved_dirs is not None and not isinstance(approved_dirs, list):
                return self._send(400, {"error": "approved_dirs must be a list"})
            _stubs.update_config(provider=provider, model=model,
                                 approved_dirs=approved_dirs)
            _stubs.audit_log("user", "config_updated",
                             f"provider={provider} model={model} "
                             f"approved_dirs={approved_dirs}")
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})


def create_server(port: int | None = None) -> ThreadingHTTPServer:
    port = port or int(os.environ.get("CEZERI_PORT", DEFAULT_PORT))
    # Localhost only — never bind 0.0.0.0.
    return ThreadingHTTPServer(("127.0.0.1", port), _Handler)


def main() -> None:
    server = create_server()
    _stubs.audit_log("system", "server_start",
                     f"listening on 127.0.0.1:{server.server_address[1]}")
    print(f"Cezeri sidecar v{VERSION} on http://127.0.0.1:{server.server_address[1]}",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _stubs.audit_log("system", "server_stop", "sidecar shutting down")
        server.server_close()


if __name__ == "__main__":
    main()

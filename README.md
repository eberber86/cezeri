# Cezeri — Phase 1

A desktop app where a virology researcher directs a team of AI domain experts
that work together on real research tasks. Named after El-Cezeri (Al-Jazari),
the 12th-century scholar who built programmable automata.

Phase 1: Tauri shell + React/TypeScript frontend, Python agent-runtime
sidecar (orchestrator + 3 specialists: **viral immunologist**,
**molecular virologist**, **scientific writer**), literature search
(PubMed / Semantic Scholar / Europe PMC) with mandatory citations, scoped
file tools behind a permission gate, and a full audit log.

## Layout

```
cezeri/
  docs/CONTRACT.md        integration contract all chunks follow
  frontend/               Vite + React + TypeScript UI (Tauri shell)
  runtime/                Python sidecar (cezeri_runtime package)
  README.md               this file
  SETUP.md                dev-mode setup (API key, WSL2/Python, folders)
```

## Quick dev run (Windows)

1. Follow [SETUP.md](SETUP.md) once (Python, API key, approved folders).
2. Terminal 1 — sidecar:
   `cd runtime && python -m cezeri_runtime.server`
3. Terminal 2 — UI:
   `cd frontend && npm install && npm run dev`
4. Open http://127.0.0.1:5173 — chat with the team, approve file writes,
   watch plans progress per agent.

## Safety model

- Agents can only read/write inside **user-approved folders** (managed in
  Settings). Everything else raises `PermissionError` and is audit-logged.
- File writes and code execution are **proposed, never performed**: the UI
  shows an approval card (summary + preview) and the agent waits.
- Every scientific claim must carry a **citation** from the literature tools.
- Append-only **audit log** records every tool call, approval, file access,
  and LLM call (provider + model only — never keys or prompt content).
- Nothing phones home: literature APIs are the only network calls besides
  the configured LLM provider.

## What's stubbed in Phase 1

- Code execution: approval + audit only, never executed.
- No push notifications, DMs, personal knowledge-base RAG, custom agent
  builder UI, or document generation (Phase 2/3).
- Packaged `.msi` build: Tauri config is ready (`src-tauri/tauri.conf.json`)
  but the installer itself is built on a Windows machine with the Tauri CLI.

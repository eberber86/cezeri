# Cezeri Phase 1 — Integration Contract

All chunks must conform to this contract. Working dir: `~/workspace/cezeri`.

## Layout
```
~/workspace/cezeri/
  docs/CONTRACT.md            (this file)
  README.md                   (integration worker writes)
  SETUP.md                    (integration worker writes)
  .gitignore
  frontend/                   (Worker 1: Vite + React + TypeScript)
    package.json, tsconfig.json, vite.config.ts
    index.html, src/...
    src-tauri/tauri.conf.json (sidecar points at ../runtime)
  runtime/                    (Workers 2-4: Python package)
    requirements.txt          (keep minimal: requests)
    cezeri_runtime/
      __init__.py
      config.py               (W4: env + key-file config, approved dirs)
      llm.py                  (W2: provider-agnostic chat + ReAct loop)
      agents.py               (W2: orchestrator + 3 specialist role prompts)
      orchestrator.py         (W2: plan/step engine)
      server.py               (W2: HTTP API below, stdlib http.server)
      approvals.py            (W4: permission-gate store)
      audit.py                (W4: JSONL audit log)
      tools/
        __init__.py
        literature.py         (W3: PubMed / Semantic Scholar / Europe PMC)
        files.py              (W4: scoped file tools)
```

## Sidecar HTTP API — http://127.0.0.1:8765 (configurable via CEZERI_PORT)

All JSON. No auth (localhost-only); never bind 0.0.0.0.

- `GET /health` → `{"status":"ok","version":"0.1.0","provider":"anthropic"}`
- `POST /chat` — body `{"target":"team"|"viral_immunologist"|"molecular_virologist"|"scientific_writer","message":"..."}`
  → `{"plan_id":"...","status":"running"}` (frontend polls the plan)
- `GET /plans` → `{"plans":[{"id","title","status","created_at"}]}`
- `GET /plans/{id}` → full plan (schema below)
- `GET /approvals?status=pending` → `{"approvals":[...]}`
- `POST /approvals/{id}/decision` — body `{"approved":true|false,"note":""}` → `{"ok":true}`
- `GET /audit?limit=200` → `{"entries":[...]}`
- `GET /config` → `{"provider","model","approved_dirs":[...],"has_key":true|false}` (NEVER return the key)
- `PUT /config` — body `{"provider":"anthropic","model":"...","approved_dirs":[...]}` → `{"ok":true}`
- `POST /key` — body `{"api_key":"..."}` → stores to key file 0600, `{"ok":true}`

### Plan schema
```json
{
  "id": "pl_abc123", "title": "Review manuscript section",
  "target": "team", "status": "running",
  "steps": [
    {"id":"st_1","agent":"viral_immunologist","label":"Assess immunological claims",
     "status":"done","detail":"...","result":"..."},
    {"id":"st_2","agent":"molecular_virologist","label":"Check methods",
     "status":"awaiting_approval","detail":"wants to write notes.md","result":null}
  ],
  "created_at": "2026-10-01T13:00:00Z"
}
```
Step status ∈ `pending|running|awaiting_approval|done|failed|skipped`.
Plan status ∈ `queued|running|awaiting_approval|done|failed`.

### Approval schema
```json
{"id":"ap_x","plan_id":"pl_abc","step_id":"st_2","kind":"file_write",
 "summary":"Write /approved/notes.md (42 lines)",
 "payload_preview":"first 500 chars...",
 "status":"pending","created_at":"..."}
```
kind ∈ `file_write|code_exec`.

### Audit entry
```json
{"ts":"...","actor":"viral_immunologist","action":"tool_call",
 "detail":"search_pubmed('influenza HAI correlate') -> 8 papers","plan_id":"pl_abc"}
```
actor ∈ `orchestrator|viral_immunologist|molecular_virologist|scientific_writer|system|user`.

## LLM layer (W2) — provider-agnostic
- `llm.py` exposes `chat(messages: list[{"role","content"}]) -> str` (plain text, no streaming).
- Provider chosen by config `provider ∈ anthropic|openai|gemini|kimi`; API key from env `CEZERI_API_KEY` or key file. **No key in code, logs, or audit.**
- Agent loop is ReAct-over-text (uniform across providers): system prompt tells the
  model to emit tool calls as fenced blocks:
  ```` ```tool {"name":"search_pubmed","args":{"query":"...","max_results":8}}``` ````
  Runtime parses, executes via the tool registry, appends `TOOL RESULT:` and continues.
  Model ends turn with `FINAL:` followed by the user-facing answer.
- Anthropic adapter implemented fully (primary). OpenAI + Gemini adapters implement
  the same `chat()` interface (mapped to their chat-completions endpoints).

## Tool registry
Runtime keeps `TOOLS: dict[str, callable]` shared by orchestrator and specialists.
- W3 registers: `search_pubmed`, `search_semantic_scholar`, `search_europe_pmc`,
  `format_citations`. Paper dict: `{title,authors,year,journal,doi,pmid,url,abstract}`.
  All search tools take `(query: str, max_results: int = 8)` and MUST return `[]`
  (not raise) when offline or rate-limited.
- W4 registers: `read_file`, `list_dir`, `propose_write` (creates approval, pauses
  step), `propose_exec` (creates approval for code execution; Phase 1: execution
  itself is stubbed — approval + audit only, no actual exec).

## Scoped files (W4)
- Every file path is resolved to absolute and MUST be inside an approved dir,
  else raise `PermissionError` (and audit the denial).
- Approved dirs: env `CEZERI_APPROVED_DIRS` (os.pathsep-separated) or config file;
  UI manages via `PUT /config`.
- Writes NEVER happen directly: agent calls `propose_write` → approval created →
  step `awaiting_approval` → UI decision → on approve, runtime writes + audits.

## Audit (W4)
- Append-only JSONL at the runtime data dir (`~/.cezeri/audit.jsonl` or
  `%APPDATA%/Cezeri` on Windows — resolve per-OS in config.py).
- Log: server start/stop, every tool call (name + redacted args), every approval
  proposed/decided, every file read/write, every LLM call (provider+model only,
  no prompt/key content).

## Frontend (W1)
- Views: Chat (target selector: Team + 3 specialists), Plans (list + detail with
  per-agent step progress), Approvals (pending list, Approve/Deny), Audit (table),
  Settings (provider select, model text, API key password field → POST /key,
  approved folders add/remove → PUT /config).
- Talks to sidecar base URL from a single `src/lib/api.ts`; graceful "sidecar not
  running" banner with instructions.
- `src-tauri/tauri.conf.json`: app name `Cezeri`, identifier `com.cezeri.app`,
  sidecar config referencing the Python runtime (dev: external runner note).
- Dev mode must work in a browser: `npm install && npm run dev`.

## Non-goals for Phase 1 (stub, don't build)
- Actual code execution (approve+log only), push notifications, DMs, personal
  knowledge-base RAG, custom agent builder UI, document generation, EAS/.msi build.

# Cezeri — Setup (dev mode, Windows-first)

## 1. Python runtime

- Install **Python 3.10+** on Windows. The smooth path is **WSL2**
  (Ubuntu) — the agent runtime was developed against Linux/macOS paths and
  WSL2 avoids Windows path quirks. Native Windows Python also works.
- In WSL2/terminal:
  ```
  cd ~/workspace/cezeri/runtime
  python3 -m venv .venv && source .venv/bin/activate   # WSL2
  pip install -r requirements.txt                      # (only `requests`)
  ```

## 2. LLM API key (required for the agents to think)

The app is provider-agnostic; **Anthropic (Claude Sonnet-class)** is the
suggested default. Usage is billed to your own key.

Pick one — the app never stores the key anywhere except the local key file:

- **Option A — Settings UI:** start the sidecar + UI (step 4), open
  Settings, paste the key, Save. It is written to the OS key file
  (`%APPDATA%/Cezeri/api_key`, mode 0600) and never displayed again.
- **Option B — environment variable:** `set CEZERI_API_KEY=sk-ant-...`
  (or `$env:CEZERI_API_KEY=...` in PowerShell) before starting the sidecar.

Switch provider anytime in Settings (Anthropic / OpenAI / Gemini) or via
`CEZERI_PROVIDER`. Optional: `CEZERI_MODEL` to pin a model name.

Without a key, the sidecar runs fine — literature search, file tools,
approvals, and audit all work — but any chat plan fails fast with a clear
"API key not configured" message instead of calling the model.

## 3. Approved folders

Agents may touch files **only** inside folders you approve. Configure in
Settings → Approved folders, or via env:

```
set CEZERI_APPROVED_DIRS=C:\Users\you\papers;C:\Users\you\notes
```

Start with one folder (e.g. a `Cezeri-work` folder). Reads work
immediately; writes always pop an approval card first.

## 4. Run it

Terminal 1 — sidecar (leave running):
```
cd ~/workspace/cezeri/runtime
python -m cezeri_runtime.server
# → Cezeri sidecar v0.1.0 on http://127.0.0.1:8765
```

Terminal 2 — UI:
```
cd ~/workspace/cezeri/frontend
npm install
npm run dev
# → http://127.0.0.1:5173
```

The UI shows a "Sidecar not running" banner until terminal 1 is up.

## 5. Try it

1. In Chat, pick **Team** and ask e.g.:
   "What assays would you run to compare neutralizing antibody durability
   after mRNA vs protein-subunit COVID boosters?"
2. Open **Plans** to watch per-agent steps; specialists will call the
   literature tools and cite papers.
3. Ask a specialist to save notes to a file in your approved folder, then
   approve/deny the card in **Approvals**.
4. Check **Audit** — every tool call, approval, and file access is there.

## Troubleshooting

- `API key not configured` → step 2.
- Literature tools return nothing → offline or rate-limited (Semantic
  Scholar rate-limits aggressively); the agents degrade gracefully.
- Port clash → `set CEZERI_PORT=8770` (and update the UI's
  `src/lib/api.ts` `SIDECAR_BASE_URL`).

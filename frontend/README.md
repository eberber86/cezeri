# Cezeri frontend

Vite + React + TypeScript UI for the Cezeri desktop app (Tauri shell).
Talks to the Python sidecar at `http://127.0.0.1:8765`
(one constant, `SIDECAR_BASE_URL`, in `src/lib/api.ts`).

## Dev mode (browser)

```sh
npm install
npm run dev
```

Open http://127.0.0.1:5173. The UI works in a plain browser and talks
directly to the sidecar. If the sidecar is not running, a banner appears
with instructions to start it:

```sh
cd ~/workspace/cezeri/runtime && python -m cezeri_runtime.server
```

## Build

```sh
npm run build     # typechecks (tsc --noEmit) then builds into dist/
npm run typecheck # tsc --noEmit only
```

## Tauri

`src-tauri/tauri.conf.json` configures the desktop shell: app name "Cezeri",
identifier `com.cezeri.app`, window 1280x860, and a sidecar entry
(`bundle.externalBin: bin/cezeri-sidecar`) that launches the Python runtime.
In dev mode the sidecar is started separately (see above); Tauri's
`beforeDevCommand` serves the frontend with `npm run dev`.

Note: the comment at the top of `tauri.conf.json` documents the dev-mode
sidecar setup. If a strict JSON parser is used anywhere, move that text
into a `"_comment"` field or strip it before parsing.

## Dependencies

Kept minimal on purpose: `react`, `react-dom`, `vite`, `typescript`
(plus `@types/react`, `@types/react-dom` for the typecheck). No UI framework;
styling is hand-rolled CSS in `src/styles.css`.

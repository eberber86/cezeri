"""Provider-agnostic LLM layer for the Cezeri runtime.

Exposes:
    chat(messages) -> str
        Plain-text, non-streaming chat. Provider comes from config
        (`anthropic` | `openai` | `gemini` | `kimi`); the API key comes from env
        `CEZERI_API_KEY` or the key file (via the config module / fallback).

        Raises LLMError with a clear "API key not configured" message when
        no key is available — the whole runtime works without a key.

ReAct helpers shared by the orchestrator:
    extract_tool_calls(text) -> list[{"name", "args"}]
        Parses fenced ```` ```tool {"name":"...","args":{...}}``` ```` blocks.
    strip_tool_blocks(text) -> str
        Removes those blocks so the visible answer can be extracted.

Privacy: the key and prompt content are NEVER logged. Only provider+model
go to the audit log.
"""

from __future__ import annotations

import json
import re

import requests

from cezeri_runtime import _stubs


class LLMError(Exception):
    """Raised for any LLM-layer failure (no key, bad provider, HTTP error)."""


_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
# Gemini via its OpenAI-compatible chat-completions endpoint (same interface).
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
# Kimi (Moonshot AI) via its OpenAI-compatible endpoint.
_KIMI_URL = "https://api.moonshot.ai/v1/chat/completions"

_TIMEOUT = 120

_TOOL_RE = re.compile(r"```tool\s*(\{.*?\})\s*```", re.DOTALL)


# ------------------------------------------------------------- public API

def chat(messages: list[dict]) -> str:
    """Send `messages` ({"role","content"}) and return plain text."""
    provider = _stubs.get_provider().strip().lower()
    model = _stubs.get_model()
    key = _stubs.get_api_key()
    if not key:
        raise LLMError(
            "API key not configured. Set the CEZERI_API_KEY environment variable, "
            "add a key via Settings (POST /key), or place it in the key file."
        )
    # Audit: provider + model only — never the key or prompt content.
    _stubs.audit_log("system", "llm_call", f"provider={provider} model={model}")
    if provider == "anthropic":
        return _anthropic_chat(key, model, messages)
    if provider == "openai":
        return _openai_chat(key, model, messages, _OPENAI_URL, "OpenAI")
    if provider == "gemini":
        return _openai_chat(key, model, messages, _GEMINI_URL, "Gemini")
    if provider == "kimi":
        return _openai_chat(key, model, messages, _KIMI_URL, "Kimi")
    raise LLMError(f"Unknown provider {provider!r}: expected anthropic|openai|gemini|kimi.")


def extract_tool_calls(text: str) -> list[dict]:
    """Parse ```` ```tool {"name":"...","args":{...}}``` ```` blocks."""
    calls: list[dict] = []
    for m in _TOOL_RE.finditer(text or ""):
        try:
            obj = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("name"), str):
            calls.append({"name": obj["name"], "args": obj.get("args") or {}})
    return calls


def strip_tool_blocks(text: str) -> str:
    """Remove fenced tool blocks, leaving the human-readable remainder."""
    return _TOOL_RE.sub("", text or "").strip()


# -------------------------------------------------------------- adapters

def _anthropic_chat(key: str, model: str, messages: list[dict]) -> str:
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    rest = [
        {"role": "assistant" if m.get("role") == "assistant" else "user",
         "content": m.get("content", "")}
        for m in messages if m.get("role") != "system"
    ]
    body: dict = {"model": model, "max_tokens": 4096, "messages": rest}
    if system_parts:
        body["system"] = "\n\n".join(system_parts)
    resp = requests.post(
        _ANTHROPIC_URL,
        headers={
            "x-api-key": key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        json=body,
        timeout=_TIMEOUT,
    )
    if resp.status_code != 200:
        raise LLMError(f"Anthropic API error {resp.status_code}: {resp.text[:500]}")
    try:
        data = resp.json()
        return "".join(b.get("text", "") for b in data.get("content", [])
                       if b.get("type") == "text").strip()
    except (ValueError, AttributeError) as e:
        raise LLMError(f"Anthropic: could not parse response ({e}).")


def _openai_chat(key: str, model: str, messages: list[dict], url: str, label: str) -> str:
    norm = [
        {"role": "assistant" if m.get("role") == "assistant" else
                 ("system" if m.get("role") == "system" else "user"),
         "content": m.get("content", "")}
        for m in messages
    ]
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
        json={"model": model, "messages": norm},
        timeout=_TIMEOUT,
    )
    if resp.status_code != 200:
        raise LLMError(f"{label} API error {resp.status_code}: {resp.text[:500]}")
    try:
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except (ValueError, KeyError, IndexError, AttributeError) as e:
        raise LLMError(f"Chat-completions: could not parse response ({e}).")

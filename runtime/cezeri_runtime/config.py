"""Configuration for the Cezeri runtime sidecar.

Settings come from environment variables, with a JSON config file
(``<data-dir>/config.json``) overriding env values per key:

- ``CEZERI_PROVIDER``      default ``"anthropic"``
- ``CEZERI_MODEL``         sensible default per provider
- ``CEZERI_API_KEY``       also readable from a 0600 key file; never exposed
                           via :func:`get_public_config`
- ``CEZERI_APPROVED_DIRS`` os.pathsep-separated list
- ``CEZERI_PORT``          default ``8765``

Data dir: ``%APPDATA%/Cezeri`` on Windows, ``~/.cezeri`` elsewhere.
"""

from __future__ import annotations

import json
import os
import sys

DEFAULT_PORT = 8765
DEFAULT_PROVIDER = "anthropic"
VALID_PROVIDERS = ("anthropic", "openai", "gemini", "kimi")

MODEL_DEFAULTS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-5",
    "gemini": "gemini-3.8-flash",
    "kimi": "kimi-k2",
}

CONFIG_FILENAME = "config.json"
KEY_FILENAME = "api_key"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def data_dir() -> str:
    """Per-OS data directory; created on demand."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "Cezeri")
    else:
        path = os.path.join(os.path.expanduser("~"), ".cezeri")
    os.makedirs(path, exist_ok=True)
    return path


def config_path() -> str:
    return os.path.join(data_dir(), CONFIG_FILENAME)


def key_path() -> str:
    return os.path.join(data_dir(), KEY_FILENAME)


# ---------------------------------------------------------------------------
# Config file helpers
# ---------------------------------------------------------------------------

def _load_file_config() -> dict:
    try:
        with open(config_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_file_config(data: dict) -> None:
    path = config_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def normalize_dir(path: str) -> str:
    """Expand, absolutize and normalize a directory path."""
    p = os.path.abspath(os.path.expanduser(path))
    p = os.path.normpath(p)
    return os.path.normcase(p) if sys.platform == "win32" else p


def _env_or_file(env_name: str, file_key: str, default=None, parse=None):
    """Config file value wins; else env var (optionally parsed); else default."""
    file_cfg = _load_file_config()
    if file_key in file_cfg and file_cfg[file_key] is not None:
        return file_cfg[file_key]
    raw = os.environ.get(env_name)
    if raw is None or raw == "":
        return default
    return parse(raw) if parse else raw


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_provider() -> str:
    provider = _env_or_file("CEZERI_PROVIDER", "provider", DEFAULT_PROVIDER)
    provider = str(provider).strip().lower()
    return provider if provider in VALID_PROVIDERS else DEFAULT_PROVIDER


def get_model() -> str:
    provider = get_provider()
    default = MODEL_DEFAULTS.get(provider, MODEL_DEFAULTS[DEFAULT_PROVIDER])
    model = _env_or_file("CEZERI_MODEL", "model", default)
    return str(model).strip() or default


def get_port() -> int:
    try:
        return int(_env_or_file("CEZERI_PORT", "port", DEFAULT_PORT))
    except (TypeError, ValueError):
        return DEFAULT_PORT


def get_approved_dirs() -> list[str]:
    """Effective approved dirs (config file overrides env), normalized."""
    file_cfg = _load_file_config()
    if isinstance(file_cfg.get("approved_dirs"), list):
        raw_dirs = file_cfg["approved_dirs"]
    else:
        raw_dirs = os.environ.get("CEZERI_APPROVED_DIRS", "").split(os.pathsep)
    seen: list[str] = []
    for d in raw_dirs:
        if not isinstance(d, str) or not d.strip():
            continue
        nd = normalize_dir(d)
        if nd not in seen:
            seen.append(nd)
    return seen


def get_public_config() -> dict:
    """Safe-for-UI config. NEVER includes the API key."""
    return {
        "provider": get_provider(),
        "model": get_model(),
        "approved_dirs": get_approved_dirs(),
        "has_key": bool(get_api_key()),
    }


def update_config(values: dict) -> dict:
    """Merge ``values`` into the JSON config file (used by PUT /config).

    Accepted keys: ``provider``, ``model``, ``port``, ``approved_dirs``.
    Returns the resulting public config.
    """
    allowed = {"provider", "model", "port", "approved_dirs"}
    cfg = _load_file_config()
    for key, value in values.items():
        if key not in allowed:
            continue
        if key == "provider":
            value = str(value).strip().lower()
            if value not in VALID_PROVIDERS:
                raise ValueError(f"unknown provider: {value!r}")
        if key == "approved_dirs":
            if not isinstance(value, list):
                raise ValueError("approved_dirs must be a list of paths")
            value = [normalize_dir(d) for d in value if isinstance(d, str) and d.strip()]
        cfg[key] = value
    _save_file_config(cfg)
    return get_public_config()


def add_approved_dir(path: str) -> list[str]:
    """Add a dir to the config file's approved list (normalized)."""
    cfg = _load_file_config()
    dirs = cfg.get("approved_dirs")
    if not isinstance(dirs, list):
        dirs = []
    nd = normalize_dir(path)
    if nd not in dirs:
        dirs.append(nd)
    cfg["approved_dirs"] = dirs
    _save_file_config(cfg)
    return dirs


def remove_approved_dir(path: str) -> list[str]:
    """Remove a dir from the config file's approved list (normalized)."""
    cfg = _load_file_config()
    dirs = cfg.get("approved_dirs")
    if not isinstance(dirs, list):
        dirs = []
    nd = normalize_dir(path)
    dirs = [d for d in dirs if d != nd]
    cfg["approved_dirs"] = dirs
    _save_file_config(cfg)
    return dirs


# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------

def get_api_key() -> str | None:
    """API key from env first, then the 0600 key file."""
    env_key = os.environ.get("CEZERI_API_KEY", "").strip()
    if env_key:
        return env_key
    try:
        with open(key_path(), "r", encoding="utf-8") as fh:
            key = fh.read().strip()
        return key or None
    except (FileNotFoundError, OSError):
        return None


def save_api_key(key: str) -> None:
    """Write the API key to the key file with mode 0600 (used by POST /key)."""
    if not isinstance(key, str) or not key.strip():
        raise ValueError("API key must be a non-empty string")
    path = key_path()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, key.strip().encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(path, 0o600)  # enforce in case the file already existed

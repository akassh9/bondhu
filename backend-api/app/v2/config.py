from __future__ import annotations

import os
from pathlib import Path


def api_mode() -> str:
    mode = os.getenv("PYTHIA_API_MODE", "dual").strip().lower()
    if mode not in {"v1", "v2", "dual"}:
        return "dual"
    return mode


def sqlite_path(backend_root: Path) -> Path:
    raw = os.getenv("PYTHIA_SQLITE_PATH", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return backend_root / "data" / "pythia_v2.sqlite3"


def agent_model() -> str:
    return os.getenv("PYTHIA_AGENT_MODEL", os.getenv("PYTHIA_LLM_MODEL", "gpt-5-codex")).strip() or "gpt-5-codex"


def enable_dual_mode() -> bool:
    return api_mode() == "dual"

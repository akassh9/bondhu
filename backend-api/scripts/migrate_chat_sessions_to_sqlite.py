#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from app.v2 import build_engine, build_session_factory, init_db, sqlite_path
from app.v2.migration import import_legacy_chat_sessions


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    db_path = sqlite_path(BACKEND_ROOT)
    engine = build_engine(db_path)
    init_db(engine)
    session_factory = build_session_factory(engine)

    legacy_dir = BACKEND_ROOT / "data" / "chat_sessions"
    result = import_legacy_chat_sessions(session_factory, legacy_dir)
    print(json.dumps({"db": str(db_path), "result": result}, indent=2))


if __name__ == "__main__":
    main()

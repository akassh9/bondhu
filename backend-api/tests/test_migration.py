import json
import sqlite3
from pathlib import Path

from app.v2 import build_engine, build_session_factory, init_db
from app.v2.migration import import_legacy_chat_sessions


def test_legacy_import_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "v2.sqlite3"
    legacy_dir = tmp_path / "chat_sessions"
    legacy_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "session_id": "abc123",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "working_spec": {"schema_version": "1.0", "events": 1000},
        "messages": [
            {"role": "user", "content": "hello", "at": "2026-01-01T00:00:00+00:00"},
            {"role": "assistant", "content": "hi", "at": "2026-01-01T00:00:01+00:00"},
        ],
    }
    (legacy_dir / "abc123.json").write_text(json.dumps(payload), encoding="utf-8")

    engine = build_engine(db_path)
    init_db(engine)
    session_factory = build_session_factory(engine)

    result1 = import_legacy_chat_sessions(session_factory, legacy_dir)
    result2 = import_legacy_chat_sessions(session_factory, legacy_dir)

    assert result1["threads"] == 1
    assert result1["messages"] == 2
    assert result2["threads"] == 0


def test_init_db_adds_workflow_intent_column_for_existing_settings_table(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE settings (
            id TEXT PRIMARY KEY,
            thread_id TEXT,
            runspec_json TEXT,
            viability TEXT,
            viability_notes_json TEXT,
            locked_at TEXT,
            created_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()

    engine = build_engine(db_path)
    init_db(engine)

    check = sqlite3.connect(db_path)
    rows = check.execute("PRAGMA table_info(settings)").fetchall()
    check.close()
    names = {row[1] for row in rows}
    assert "workflow_intent_json" in names

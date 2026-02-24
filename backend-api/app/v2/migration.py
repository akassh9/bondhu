from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from .db_models import MessageRow, MigrationRow, SettingRow, ThreadRow


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _checksum_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def import_legacy_chat_sessions(session_factory, legacy_dir: Path) -> dict[str, int]:
    imported_threads = 0
    imported_messages = 0
    imported_settings = 0

    if not legacy_dir.exists():
        return {"threads": 0, "messages": 0, "settings": 0}

    files = sorted(path for path in legacy_dir.iterdir() if path.is_file() and path.suffix == ".json")
    with session_factory() as db:
        for path in files:
            raw = path.read_bytes()
            checksum = _checksum_bytes(raw)
            migration_id = f"legacy_chat:{path.name}"

            existing = db.get(MigrationRow, migration_id)
            if existing and existing.checksum == checksum:
                continue

            payload = json.loads(raw.decode("utf-8"))
            thread_id = str(payload.get("session_id") or path.stem)

            thread = db.get(ThreadRow, thread_id)
            if thread is None:
                thread = ThreadRow(
                    id=thread_id,
                    created_at=str(payload.get("created_at") or _now_iso()),
                    updated_at=str(payload.get("updated_at") or _now_iso()),
                    status="DISCOVERY",
                )
                db.add(thread)
                imported_threads += 1

            working_spec = payload.get("working_spec") or {}
            setting_id = f"{thread_id}_legacy"
            setting = db.get(SettingRow, setting_id)
            if setting is None:
                setting = SettingRow(
                    id=setting_id,
                    thread_id=thread_id,
                    runspec_json=json.dumps(working_spec, sort_keys=True),
                    workflow_intent_json="{}",
                    viability="unknown",
                    viability_notes_json="[]",
                    locked_at=None,
                    created_at=str(payload.get("created_at") or _now_iso()),
                )
                db.add(setting)
                imported_settings += 1
            else:
                setting.runspec_json = json.dumps(working_spec, sort_keys=True)
                if not setting.workflow_intent_json:
                    setting.workflow_intent_json = "{}"

            thread.active_setting_id = setting_id

            old_messages_stmt = select(MessageRow).where(MessageRow.thread_id == thread_id)
            for row in db.execute(old_messages_stmt).scalars().all():
                db.delete(row)

            for msg in payload.get("messages", []):
                db.add(
                    MessageRow(
                        thread_id=thread_id,
                        role=str(msg.get("role") or "system"),
                        content=str(msg.get("content") or ""),
                        agent_name="legacy-import",
                        trace_id=None,
                        created_at=str(msg.get("at") or _now_iso()),
                    )
                )
                imported_messages += 1

            migration_row = db.get(MigrationRow, migration_id)
            if migration_row is None:
                db.add(MigrationRow(id=migration_id, checksum=checksum, applied_at=_now_iso()))
            else:
                migration_row.checksum = checksum
                migration_row.applied_at = _now_iso()

        db.commit()

    return {"threads": imported_threads, "messages": imported_messages, "settings": imported_settings}

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .db_models import Base


def build_engine(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite+pysqlite:///{path}", future=True)


def build_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)


def _ensure_settings_columns(engine) -> None:
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(settings)").mappings().all()
        column_names = {str(row.get("name")) for row in rows}

        if "workflow_intent_json" not in column_names:
            conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN workflow_intent_json TEXT DEFAULT '{}'")


def init_db(engine) -> None:
    Base.metadata.create_all(engine)
    _ensure_settings_columns(engine)

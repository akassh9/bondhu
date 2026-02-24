from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ThreadRow(Base):
    __tablename__ = "threads"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    status: Mapped[str] = mapped_column(String(32), default="DISCOVERY")
    active_setting_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    messages: Mapped[list[MessageRow]] = relationship(back_populates="thread", cascade="all, delete-orphan")
    settings: Mapped[list[SettingRow]] = relationship(back_populates="thread", cascade="all, delete-orphan")


class MessageRow(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(String(64), ForeignKey("threads.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    agent_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[str] = mapped_column(String(64), default=_now_iso)

    thread: Mapped[ThreadRow] = relationship(back_populates="messages")


class SettingRow(Base):
    __tablename__ = "settings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), ForeignKey("threads.id"), index=True)
    runspec_json: Mapped[str] = mapped_column(Text)
    workflow_intent_json: Mapped[str] = mapped_column(Text, default="{}")
    viability: Mapped[str] = mapped_column(String(32), default="unknown")
    viability_notes_json: Mapped[str] = mapped_column(Text, default="[]")
    locked_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[str] = mapped_column(String(64), default=_now_iso)

    thread: Mapped[ThreadRow] = relationship(back_populates="settings")
    workflows: Mapped[list[WorkflowRow]] = relationship(back_populates="setting", cascade="all, delete-orphan")


class WorkflowRow(Base):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    setting_id: Mapped[str] = mapped_column(String(64), ForeignKey("settings.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    schema_version: Mapped[str] = mapped_column(String(32), default="1.0")
    graph_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now_iso)

    setting: Mapped[SettingRow] = relationship(back_populates="workflows")
    runs: Mapped[list[WorkflowRunRow]] = relationship(back_populates="workflow", cascade="all, delete-orphan")


class WorkflowRunRow(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(64), ForeignKey("workflows.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state: Mapped[str] = mapped_column(String(32), default="CREATED")
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now_iso)

    workflow: Mapped[WorkflowRow] = relationship(back_populates="runs")
    node_runs: Mapped[list[NodeRunRow]] = relationship(back_populates="workflow_run", cascade="all, delete-orphan")


class NodeRunRow(Base):
    __tablename__ = "node_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_run_id: Mapped[str] = mapped_column(String(64), ForeignKey("workflow_runs.id"), index=True)
    node_id: Mapped[str] = mapped_column(String(64))
    node_type: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32), default="CREATED")
    output_json: Mapped[str] = mapped_column(Text, default="{}")
    artifact_index_json: Mapped[str] = mapped_column(Text, default="[]")

    workflow_run: Mapped[WorkflowRunRow] = relationship(back_populates="node_runs")


class MigrationRow(Base):
    __tablename__ = "migrations"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    applied_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    checksum: Mapped[str] = mapped_column(String(256))

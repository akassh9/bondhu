from __future__ import annotations

from typing import Any

from .thread_service import V2ThreadService


def to_legacy_session_state(thread_payload: dict[str, Any]) -> dict[str, Any]:
    setting = thread_payload.get("setting") or {}
    messages = thread_payload.get("messages", [])
    return {
        "session_id": thread_payload.get("id"),
        "created_at": thread_payload.get("created_at"),
        "updated_at": thread_payload.get("updated_at"),
        "working_spec": setting.get("runspec"),
        "proposed_spec": None,
        "proposed_diff": [],
        "messages": [
            {
                "role": message.get("role"),
                "content": message.get("content"),
                "at": message.get("created_at"),
            }
            for message in messages
        ],
        "last_run_id": None,
    }


class LegacyChatAdapter:
    def __init__(self, thread_service: V2ThreadService) -> None:
        self.thread_service = thread_service

    def create_session(self, initial_spec: dict[str, Any] | None) -> dict[str, Any]:
        thread = self.thread_service.create_thread(initial_spec)
        return to_legacy_session_state(thread.model_dump())

    def get_session(self, session_id: str) -> dict[str, Any]:
        thread = self.thread_service.get_thread(session_id)
        return to_legacy_session_state(thread.model_dump())

    def post_message(self, session_id: str, message: str) -> dict[str, Any]:
        result = self.thread_service.post_message(session_id, message)
        return {
            "assistant_message": result.assistant_message,
            "proposal_summary": result.proposal_summary,
            "run_recommended": result.run_recommended,
            "proposed_spec": None,
            "proposal_diff": [],
            "cmnd_preview": self.thread_service.compile_active_spec_preview(session_id),
            "validation_error": None,
            "model": "agentic-v2",
            "session": to_legacy_session_state(result.thread.model_dump()),
        }

    def apply(self, session_id: str) -> dict[str, Any]:
        thread = self.thread_service.get_thread(session_id)
        setting = thread.setting
        if setting is None:
            raise ValueError("no active setting")
        locked = self.thread_service.lock_setting(setting.id)
        refreshed = self.thread_service.get_thread(session_id)
        return {
            "applied": True,
            "locked_setting_id": locked.id,
            "session": to_legacy_session_state(refreshed.model_dump()),
        }

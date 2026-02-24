from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..chat_service import _deep_merge, _sanitize_proposal_patch
from ..compiler import compile_runspec_to_text
from ..models import RunSpec
from ..policy import validate_policy
from .agents_runtime import AgentRuntime
from .db_models import MessageRow, SettingRow, ThreadRow
from .schemas import MessageResponse, SettingResponse, ThreadMessageResponse, ThreadResponse
from .viability import evaluate_physics_viability

LOGGER = logging.getLogger(__name__)


class ThreadNotFoundError(FileNotFoundError):
    pass


class SettingNotFoundError(FileNotFoundError):
    pass


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sanitize_workflow_intent(intent: Any) -> dict[str, Any]:
    if not isinstance(intent, dict):
        return {}

    out: dict[str, Any] = {}
    has_signal = False

    summary = str(intent.get("summary") or "").strip()
    if summary:
        out["summary"] = summary[:600]
        has_signal = True

    if "needs_workflow_stage" in intent:
        out["needs_workflow_stage"] = bool(intent.get("needs_workflow_stage"))
        has_signal = True

    particle_filter = intent.get("particle_filter")
    if isinstance(particle_filter, dict):
        pdg_values: list[int] = []
        for value in particle_filter.get("pdg", []):
            parsed = _to_int(value)
            if parsed is None:
                continue
            if parsed not in pdg_values:
                pdg_values.append(parsed)
        if pdg_values:
            out["particle_filter"] = {
                "pdg": pdg_values[:16],
                "final_only": bool(particle_filter.get("final_only", True)),
            }
            has_signal = True

    kinematic_cut = intent.get("kinematic_cut")
    if isinstance(kinematic_cut, dict):
        cut_out: dict[str, float] = {}
        for key in ("pt_min", "pt_max", "eta_min", "eta_max", "phi_min", "phi_max", "mass_min", "mass_max"):
            parsed = _to_float(kinematic_cut.get(key))
            if parsed is not None:
                cut_out[key] = parsed
        if cut_out:
            out["kinematic_cut"] = cut_out
            has_signal = True

    histogram = intent.get("histogram_1d")
    if isinstance(histogram, dict):
        field = str(histogram.get("field") or "pt").strip().lower()
        if field not in {"pt", "eta", "phi", "mass", "energy"}:
            field = "pt"

        bins = _to_int(histogram.get("bins"))
        if bins is None:
            bins = 20
        bins = min(200, max(1, bins))

        hmin = _to_float(histogram.get("min"))
        hmax = _to_float(histogram.get("max"))
        if hmin is None:
            hmin = 0.0
        if hmax is None or hmax <= hmin:
            hmax = hmin + 1.0

        out["histogram_1d"] = {
            "field": field,
            "bins": bins,
            "min": hmin,
            "max": hmax,
        }
        has_signal = True

    if "include_cutflow" in intent:
        out["include_cutflow"] = bool(intent.get("include_cutflow", False))
        has_signal = True

    raw_formats = intent.get("export_formats")
    export_formats: list[str] = []
    if isinstance(raw_formats, list):
        for fmt in raw_formats:
            normalized = str(fmt).strip().lower()
            if normalized in {"json", "csv", "png"} and normalized not in export_formats:
                export_formats.append(normalized)
    if export_formats:
        out["export_formats"] = export_formats
        has_signal = True

    unavailable: list[str] = []
    raw_unavailable = intent.get("unavailable_requests")
    if isinstance(raw_unavailable, list):
        for line in raw_unavailable:
            text = str(line).strip()
            if text and text not in unavailable:
                unavailable.append(text)
    if "png" in export_formats:
        note = "PNG export is not currently supported in workflow execution; use JSON/CSV export."
        if note not in unavailable:
            unavailable.append(note)
    if unavailable:
        out["unavailable_requests"] = unavailable[:8]
        has_signal = True

    if not has_signal:
        return {}
    if "needs_workflow_stage" not in out:
        out["needs_workflow_stage"] = True
    if "include_cutflow" not in out:
        out["include_cutflow"] = False
    if "export_formats" not in out:
        out["export_formats"] = []

    return out


def _load_prompt() -> str:
    return (
        "You are a multi-agent PYTHIA planning coordinator.\n"
        "Simulate these specialists in your reasoning: ConversationAgent, PhysicsViabilityAgent, RunSpecAgent.\n"
        "You can directly update RunSpec only; workflow graph edits happen in the next workflow page.\n"
        "When users ask for workflow operations (particle tracking, cuts, histograms, cutflow, output files), "
        "acknowledge they will be configured in workflow step and populate workflow_intent accordingly.\n"
        "For unsupported workflow output requests (for example PNG file export), keep workflow_intent.export_formats "
        "as requested but also explain the limitation in workflow_intent.unavailable_requests.\n"
        "Return strict JSON only matching schema.\n"
        "proposed_spec_json must be a JSON object patch string.\n"
        "Use setting_state DISCOVERY until enough details exist; SETTING_DRAFT when partially specified; "
        "SETTING_READY when beams/processes/energy/events are coherent and policy-valid.\n"
        "Be conservative and physically plausible."
    )


class V2ThreadService:
    def __init__(self, session_factory, model: str) -> None:
        self._session_factory = session_factory
        self._runtime = AgentRuntime(model=model)
        self._prompt = _load_prompt()
        self._lock = threading.Lock()

    def create_thread(self, initial_spec: dict[str, Any] | None = None) -> ThreadResponse:
        with self._session_factory() as db:
            thread_id = uuid.uuid4().hex[:12]
            now = _now_iso()
            thread = ThreadRow(id=thread_id, created_at=now, updated_at=now, status="DISCOVERY")
            db.add(thread)

            spec = initial_spec or RunSpec().model_dump()
            viability, notes = evaluate_physics_viability(spec)
            setting = SettingRow(
                id=uuid.uuid4().hex[:12],
                thread_id=thread_id,
                runspec_json=json.dumps(spec, sort_keys=True),
                workflow_intent_json="{}",
                viability=viability,
                viability_notes_json=json.dumps(notes),
                created_at=now,
            )
            thread.active_setting_id = setting.id
            db.add(setting)
            db.commit()

            return self._build_thread_response(db, thread_id)

    def get_thread(self, thread_id: str) -> ThreadResponse:
        with self._session_factory() as db:
            return self._build_thread_response(db, thread_id)

    def get_setting(self, setting_id: str) -> SettingResponse:
        with self._session_factory() as db:
            setting = db.get(SettingRow, setting_id)
            if setting is None:
                raise SettingNotFoundError(setting_id)
            return self._to_setting_response(setting)

    def lock_setting(self, setting_id: str) -> SettingResponse:
        with self._session_factory() as db:
            setting = db.get(SettingRow, setting_id)
            if setting is None:
                raise SettingNotFoundError(setting_id)
            if setting.locked_at is None:
                setting.locked_at = _now_iso()
                thread = db.get(ThreadRow, setting.thread_id)
                if thread is not None:
                    thread.status = "SETTING_LOCKED"
                    thread.updated_at = _now_iso()
                db.commit()
            return self._to_setting_response(setting)

    def post_message(self, thread_id: str, text: str) -> ThreadMessageResponse:
        with self._lock:
            with self._session_factory() as db:
                thread = db.get(ThreadRow, thread_id)
                if thread is None:
                    raise ThreadNotFoundError(thread_id)

                setting = self._require_active_setting(db, thread)
                working_spec = json.loads(setting.runspec_json)

                prev_trace = self._latest_trace_id(db, thread_id)
                turn = self._runtime.run(
                    system_prompt=self._prompt,
                    user_message=text,
                    working_spec=working_spec,
                    previous_response_id=prev_trace,
                )
                LOGGER.info(
                    "agent_step thread_id=%s agent=%s trace_id=%s status=%s",
                    thread_id,
                    "ConversationAgent",
                    turn.trace_id,
                    "completed",
                )

                patch = _sanitize_proposal_patch(turn.proposed_spec_patch)
                candidate = _deep_merge(working_spec, patch)
                try:
                    spec_obj = RunSpec.model_validate(candidate)
                    validate_policy(spec_obj)
                    normalized = spec_obj.model_dump()
                except Exception:
                    normalized = working_spec

                workflow_intent_payload = _sanitize_workflow_intent(turn.workflow_intent)
                assistant_message = turn.assistant_message
                if workflow_intent_payload.get("needs_workflow_stage"):
                    workflow_handoff = (
                        "Run settings are configured here; workflow tracking/cuts/exports are prefilled for the next Workflow step."
                    )
                    if workflow_handoff not in assistant_message:
                        assistant_message = (assistant_message.strip() + "\n\n" + workflow_handoff).strip()

                viability, notes = evaluate_physics_viability(normalized)
                setting.runspec_json = json.dumps(normalized, sort_keys=True)
                setting.workflow_intent_json = json.dumps(
                    workflow_intent_payload,
                    sort_keys=True,
                )
                setting.viability = viability
                setting.viability_notes_json = json.dumps(notes)

                recommended_state = turn.setting_state
                if recommended_state not in {"DISCOVERY", "SETTING_DRAFT", "SETTING_READY"}:
                    recommended_state = "SETTING_DRAFT"
                if setting.locked_at:
                    thread.status = "SETTING_LOCKED"
                else:
                    thread.status = recommended_state
                thread.updated_at = _now_iso()

                user_row = MessageRow(
                    thread_id=thread_id,
                    role="user",
                    content=text,
                    agent_name="ConversationAgent",
                    trace_id=turn.trace_id,
                    created_at=_now_iso(),
                )
                assistant_row = MessageRow(
                    thread_id=thread_id,
                    role="assistant",
                    content=assistant_message,
                    agent_name="ConversationAgent",
                    trace_id=turn.response_id,
                    created_at=_now_iso(),
                )
                db.add(user_row)
                db.add(assistant_row)
                db.commit()

                thread_response = self._build_thread_response(db, thread_id)
                return ThreadMessageResponse(
                    thread=thread_response,
                    assistant_message=assistant_message,
                    proposal_summary=turn.proposal_summary,
                    setting_state=thread_response.status,
                    run_recommended=bool(turn.run_recommended),
                    trace_id=turn.trace_id,
                )

    def compile_active_spec_preview(self, thread_id: str) -> str:
        with self._session_factory() as db:
            thread = db.get(ThreadRow, thread_id)
            if thread is None:
                raise ThreadNotFoundError(thread_id)
            setting = self._require_active_setting(db, thread)
            spec = RunSpec.model_validate(json.loads(setting.runspec_json))
            return compile_runspec_to_text(spec)

    def _latest_trace_id(self, db: Session, thread_id: str) -> str | None:
        stmt = (
            select(MessageRow)
            .where(MessageRow.thread_id == thread_id, MessageRow.role == "assistant")
            .order_by(MessageRow.id.desc())
            .limit(1)
        )
        row = db.execute(stmt).scalar_one_or_none()
        return row.trace_id if row is not None else None

    def _require_active_setting(self, db: Session, thread: ThreadRow) -> SettingRow:
        if not thread.active_setting_id:
            raise SettingNotFoundError("missing active setting")
        setting = db.get(SettingRow, thread.active_setting_id)
        if setting is None:
            raise SettingNotFoundError(thread.active_setting_id)
        return setting

    def _build_thread_response(self, db: Session, thread_id: str) -> ThreadResponse:
        thread = db.get(ThreadRow, thread_id)
        if thread is None:
            raise ThreadNotFoundError(thread_id)

        messages_stmt = select(MessageRow).where(MessageRow.thread_id == thread_id).order_by(MessageRow.id.asc())
        rows = list(db.execute(messages_stmt).scalars().all())

        setting = None
        if thread.active_setting_id:
            setting_row = db.get(SettingRow, thread.active_setting_id)
            if setting_row is not None:
                setting = self._to_setting_response(setting_row)

        return ThreadResponse(
            id=thread.id,
            status=thread.status,
            active_setting_id=thread.active_setting_id,
            created_at=thread.created_at,
            updated_at=thread.updated_at,
            messages=[
                MessageResponse(
                    role=row.role,
                    content=row.content,
                    agent_name=row.agent_name,
                    trace_id=row.trace_id,
                    created_at=row.created_at,
                )
                for row in rows
            ],
            setting=setting,
        )

    def _to_setting_response(self, row: SettingRow) -> SettingResponse:
        workflow_intent: dict[str, Any] = {}
        try:
            loaded_intent = json.loads(row.workflow_intent_json or "{}")
            if isinstance(loaded_intent, dict):
                workflow_intent = loaded_intent
        except json.JSONDecodeError:
            workflow_intent = {}

        return SettingResponse(
            id=row.id,
            thread_id=row.thread_id,
            runspec=json.loads(row.runspec_json),
            workflow_intent=workflow_intent,
            viability=row.viability,
            viability_notes=json.loads(row.viability_notes_json or "[]"),
            locked_at=row.locked_at,
            created_at=row.created_at,
        )

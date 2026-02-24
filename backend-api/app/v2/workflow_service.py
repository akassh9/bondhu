from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select

from ..diagnostics import maybe_generate_workflow_results_review
from .db_models import MessageRow, NodeRunRow, SettingRow, WorkflowRow, WorkflowRunRow
from .schemas import NodeRunResponse, WorkflowResponse, WorkflowRunResponse
from .workflow_executor import execute_workflow
from .workflow_validation import validate_workflow_graph

LOGGER = logging.getLogger(__name__)


class WorkflowNotFoundError(FileNotFoundError):
    pass


class WorkflowRunNotFoundError(FileNotFoundError):
    pass


class SettingNotFoundError(FileNotFoundError):
    pass


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class V2WorkflowService:
    def __init__(
        self,
        session_factory,
        *,
        workflow_root: Path,
        create_run_fn: Callable[[dict[str, Any]], tuple[str, dict[str, Any]]],
        get_run_status_fn: Callable[[str], dict[str, Any]],
        run_dir_fn: Callable[[str], Path],
    ) -> None:
        self._session_factory = session_factory
        self._workflow_root = workflow_root
        self._workflow_root.mkdir(parents=True, exist_ok=True)
        self._create_run_fn = create_run_fn
        self._get_run_status_fn = get_run_status_fn
        self._run_dir_fn = run_dir_fn

    def create_workflow(
        self,
        *,
        setting_id: str,
        name: str,
        schema_version: str,
        graph: dict[str, Any],
    ) -> WorkflowResponse:
        with self._session_factory() as db:
            setting = db.get(SettingRow, setting_id)
            if setting is None:
                raise SettingNotFoundError(setting_id)

            workflow_id = uuid.uuid4().hex[:12]
            now = _now_iso()
            row = WorkflowRow(
                id=workflow_id,
                setting_id=setting_id,
                name=name,
                schema_version=schema_version,
                graph_json=json.dumps(graph, sort_keys=True),
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.commit()

            return self._to_workflow_response(row)

    def get_workflow(self, workflow_id: str) -> WorkflowResponse:
        with self._session_factory() as db:
            row = db.get(WorkflowRow, workflow_id)
            if row is None:
                raise WorkflowNotFoundError(workflow_id)
            return self._to_workflow_response(row)

    def validate_workflow(self, workflow_id: str) -> list[str]:
        with self._session_factory() as db:
            row = db.get(WorkflowRow, workflow_id)
            if row is None:
                raise WorkflowNotFoundError(workflow_id)
            graph = json.loads(row.graph_json)
            return validate_workflow_graph(graph)

    def start_workflow_run(self, workflow_id: str, timeout_seconds: int) -> WorkflowRunResponse:
        with self._session_factory() as db:
            workflow = db.get(WorkflowRow, workflow_id)
            if workflow is None:
                raise WorkflowNotFoundError(workflow_id)
            workflow_run_id = uuid.uuid4().hex[:12]
            now = _now_iso()
            row = WorkflowRunRow(
                id=workflow_run_id,
                workflow_id=workflow_id,
                run_id=None,
                state="QUEUED",
                summary_json=json.dumps({"timeout_seconds": timeout_seconds}, sort_keys=True),
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.commit()

        thread = threading.Thread(
            target=self._execute_workflow_run,
            args=(workflow_run_id, timeout_seconds),
            daemon=True,
        )
        thread.start()
        return self.get_workflow_run(workflow_run_id)

    def get_workflow_run(self, workflow_run_id: str) -> WorkflowRunResponse:
        with self._session_factory() as db:
            row = db.get(WorkflowRunRow, workflow_run_id)
            if row is None:
                raise WorkflowRunNotFoundError(workflow_run_id)

            node_stmt = (
                select(NodeRunRow)
                .where(NodeRunRow.workflow_run_id == workflow_run_id)
                .order_by(NodeRunRow.id.asc())
            )
            node_rows = list(db.execute(node_stmt).scalars().all())

            return WorkflowRunResponse(
                id=row.id,
                workflow_id=row.workflow_id,
                run_id=row.run_id,
                state=row.state,
                summary=json.loads(row.summary_json or "{}"),
                node_runs=[
                    NodeRunResponse(
                        node_id=n.node_id,
                        node_type=n.node_type,
                        state=n.state,
                        output=json.loads(n.output_json or "{}"),
                        artifacts=json.loads(n.artifact_index_json or "[]"),
                    )
                    for n in node_rows
                ],
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

    def get_artifact_path(self, workflow_run_id: str, name: str) -> Path:
        target = (self._workflow_root / workflow_run_id / name).resolve()
        parent = (self._workflow_root / workflow_run_id).resolve()
        if target.parent != parent or not target.exists() or not target.is_file():
            raise FileNotFoundError(name)
        return target

    def _execute_workflow_run(self, workflow_run_id: str, timeout_seconds: int) -> None:
        LOGGER.info("workflow_run_start workflow_run_id=%s timeout_seconds=%s", workflow_run_id, timeout_seconds)
        with self._session_factory() as db:
            wr = db.get(WorkflowRunRow, workflow_run_id)
            if wr is None:
                return
            workflow = db.get(WorkflowRow, wr.workflow_id)
            if workflow is None:
                wr.state = "FAILED"
                wr.updated_at = _now_iso()
                wr.summary_json = json.dumps({"error": "workflow not found"}, sort_keys=True)
                db.commit()
                return

            setting = db.get(SettingRow, workflow.setting_id)
            if setting is None:
                wr.state = "FAILED"
                wr.updated_at = _now_iso()
                wr.summary_json = json.dumps({"error": "setting not found"}, sort_keys=True)
                db.commit()
                return

            graph = json.loads(workflow.graph_json)
            errors = validate_workflow_graph(graph)
            if errors:
                wr.state = "FAILED"
                wr.updated_at = _now_iso()
                wr.summary_json = json.dumps({"error": "workflow validation failed", "details": errors}, sort_keys=True)
                db.commit()
                return

            wr.state = "RUNNING"
            wr.updated_at = _now_iso()
            db.commit()

            spec = json.loads(setting.runspec_json)
            messages_stmt = (
                select(MessageRow)
                .where(MessageRow.thread_id == setting.thread_id)
                .order_by(MessageRow.id.asc())
            )
            conversation_messages = [
                {
                    "role": row.role,
                    "content": row.content,
                    "agent_name": row.agent_name,
                    "created_at": row.created_at,
                }
                for row in db.execute(messages_stmt).scalars().all()
            ]
            workflow_meta = {
                "workflow_id": workflow.id,
                "workflow_name": workflow.name,
                "workflow_schema_version": workflow.schema_version,
            }

        run_id = None
        try:
            run_id, _status = self._create_run_fn(spec)
            self._set_run_id(workflow_run_id, run_id)

            deadline = time.time() + timeout_seconds
            final_status: dict[str, Any] | None = None
            while time.time() < deadline:
                status = self._get_run_status_fn(run_id)
                state = status.get("state")
                if state in {"SUCCEEDED", "FAILED"}:
                    final_status = status
                    break
                time.sleep(1.0)

            if final_status is None:
                self._set_failed(workflow_run_id, {"error": "timeout waiting for simulation run"})
                LOGGER.warning("workflow_run_timeout workflow_run_id=%s", workflow_run_id)
                return

            run_dir = self._run_dir_fn(run_id)
            tracked = run_dir / "tracked_particles.csv"
            summary_path = run_dir / "event_summary.json"
            artifact_dir = self._workflow_root / workflow_run_id

            node_results, summary = execute_workflow(
                graph=graph,
                tracked_particles_csv=tracked,
                event_summary_path=summary_path,
                artifact_dir=artifact_dir,
            )

            payload_summary = {
                "simulation_state": final_status.get("state"),
                "simulation_run_id": run_id,
                "simulation_exit_code": final_status.get("exit_code"),
                "workflow_summary": summary,
                "workflow_meta": workflow_meta,
            }
            review = maybe_generate_workflow_results_review(
                conversation_messages=conversation_messages,
                run_spec=spec,
                simulation_status=final_status,
                workflow_graph=graph,
                workflow_node_results=node_results,
                workflow_summary=summary,
            )
            if review is not None:
                payload_summary["llm_results_review"] = review
                artifact_dir.mkdir(parents=True, exist_ok=True)
                (artifact_dir / "llm_results_review.json").write_text(
                    json.dumps(review, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

            self._set_succeeded(workflow_run_id, node_results, payload_summary)
            LOGGER.info("workflow_run_succeeded workflow_run_id=%s run_id=%s", workflow_run_id, run_id)
        except Exception as exc:  # pylint: disable=broad-except
            self._set_failed(workflow_run_id, {"error": str(exc), "run_id": run_id})
            LOGGER.exception("workflow_run_failed workflow_run_id=%s run_id=%s", workflow_run_id, run_id)

    def _set_run_id(self, workflow_run_id: str, run_id: str) -> None:
        with self._session_factory() as db:
            row = db.get(WorkflowRunRow, workflow_run_id)
            if row is None:
                return
            row.run_id = run_id
            row.updated_at = _now_iso()
            db.commit()

    def _set_failed(self, workflow_run_id: str, summary: dict[str, Any]) -> None:
        with self._session_factory() as db:
            row = db.get(WorkflowRunRow, workflow_run_id)
            if row is None:
                return
            row.state = "FAILED"
            row.updated_at = _now_iso()
            row.summary_json = json.dumps(summary, sort_keys=True)
            db.commit()

    def _set_succeeded(self, workflow_run_id: str, node_results: list[dict[str, Any]], summary: dict[str, Any]) -> None:
        with self._session_factory() as db:
            row = db.get(WorkflowRunRow, workflow_run_id)
            if row is None:
                return

            row.state = "SUCCEEDED"
            row.updated_at = _now_iso()
            row.summary_json = json.dumps(summary, sort_keys=True)

            for result in node_results:
                node_row = NodeRunRow(
                    workflow_run_id=workflow_run_id,
                    node_id=str(result.get("node_id")),
                    node_type=str(result.get("node_type")),
                    state=str(result.get("state", "SUCCEEDED")),
                    output_json=json.dumps(result.get("output", {}), sort_keys=True),
                    artifact_index_json=json.dumps(result.get("artifacts", []), sort_keys=True),
                )
                db.add(node_row)

            db.commit()

    @staticmethod
    def _to_workflow_response(row: WorkflowRow) -> WorkflowResponse:
        return WorkflowResponse(
            id=row.id,
            setting_id=row.setting_id,
            name=row.name,
            schema_version=row.schema_version,
            graph=json.loads(row.graph_json),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

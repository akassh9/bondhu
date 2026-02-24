from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.params import Query
from fastapi.responses import FileResponse
from pydantic import ValidationError

from .chat_service import ChatOrchestrator, ChatSessionStore, public_session_state
from .compiler import compile_runspec, compile_runspec_to_text
from .models import (
    ChatCreateSessionRequest,
    ChatMessageRequest,
    ChatRunRequest,
    CompileResponse,
    CreateRunRequest,
    RunSpec,
    RunSpecEnvelope,
)
from .policy import PolicyViolation, validate_policy
from .run_service import RunService
from .store import RunNotFoundError, RunStore
from .v2 import (
    V2ThreadService,
    V2WorkflowService,
    agent_model,
    api_mode,
    build_engine,
    build_session_factory,
    init_db,
    sqlite_path,
)
from .v2.compat import LegacyChatAdapter
from .v2.migration import import_legacy_chat_sessions
from .v2.schemas import (
    MessageCreateRequest,
    SettingLockResponse,
    SettingResponse,
    ThreadCreateRequest,
    ThreadMessageResponse,
    ThreadResponse,
    WorkflowCreateRequest,
    WorkflowResponse,
    WorkflowRunCreateRequest,
    WorkflowRunResponse,
    WorkflowValidationResponse,
)
from .v2.thread_service import SettingNotFoundError as V2SettingNotFoundError
from .v2.thread_service import ThreadNotFoundError
from .v2.workflow_service import (
    SettingNotFoundError as WorkflowSettingNotFoundError,
    WorkflowNotFoundError,
    WorkflowRunNotFoundError,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
RUNS_DIR = BACKEND_ROOT / "data" / "runs"
CHAT_SESSIONS_DIR = BACKEND_ROOT / "data" / "chat_sessions"
WORKFLOW_RUNS_DIR = BACKEND_ROOT / "data" / "workflow_runs"
FRONTEND_APP_DIST = REPO_ROOT / "frontend-app" / "dist"

app = FastAPI(title="PYTHIA Backend API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8765",
        "http://localhost:8765",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = RunStore(RUNS_DIR)
run_service = RunService(store=store, repo_root=REPO_ROOT, backend_root=BACKEND_ROOT)
chat_session_store = ChatSessionStore(CHAT_SESSIONS_DIR)
chat_orchestrator = ChatOrchestrator(chat_session_store)

v2_engine = build_engine(sqlite_path(BACKEND_ROOT))
init_db(v2_engine)
v2_session_factory = build_session_factory(v2_engine)
v2_thread_service = V2ThreadService(v2_session_factory, model=agent_model())
legacy_chat_adapter = LegacyChatAdapter(v2_thread_service)


def _create_run_from_payload(spec_payload: dict) -> tuple[str, dict]:
    spec = RunSpec.model_validate(spec_payload)
    _enforce_policy(spec)
    return _create_run_from_spec(spec, auto_enqueue=True)


v2_workflow_service = V2WorkflowService(
    v2_session_factory,
    workflow_root=WORKFLOW_RUNS_DIR,
    create_run_fn=_create_run_from_payload,
    get_run_status_fn=store.get_status,
    run_dir_fn=store.run_dir,
)


@app.on_event("startup")
def startup_event() -> None:
    run_service.start()
    # Idempotent import from legacy chat JSON state.
    import_legacy_chat_sessions(v2_session_factory, CHAT_SESSIONS_DIR)


@app.on_event("shutdown")
def shutdown_event() -> None:
    run_service.stop()


@app.get("/health")
def health() -> dict:
    db_path = sqlite_path(BACKEND_ROOT)
    return {
        "ok": True,
        "api_mode": api_mode(),
        "v2_db": str(db_path),
        "v2_db_exists": db_path.exists(),
    }


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "PYTHIA Backend API", "status": "ok", "mode": api_mode()}


@app.get("/app")
@app.get("/app/{full_path:path}")
def serve_frontend_app(full_path: str = ""):
    if not FRONTEND_APP_DIST.exists():
        raise HTTPException(
            status_code=404,
            detail="frontend app bundle not found; build frontend-app and serve /app routes",
        )

    candidate = (FRONTEND_APP_DIST / full_path).resolve()
    dist_root = FRONTEND_APP_DIST.resolve()
    if (
        candidate.exists()
        and candidate.is_file()
        and Path(candidate).is_relative_to(dist_root)
    ):
        return FileResponse(path=candidate)

    index_path = FRONTEND_APP_DIST / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="frontend index.html not found")
    return FileResponse(path=index_path)


@app.get("/runspec/schema")
def runspec_schema() -> dict:
    return RunSpec.model_json_schema()


@app.post("/runspec/validate")
def validate_runspec(payload: RunSpecEnvelope) -> dict:
    spec = payload.spec
    _enforce_policy(spec)
    return {"valid": True, "normalized_spec": spec.model_dump()}


@app.post("/runspec/compile", response_model=CompileResponse)
def compile_spec(payload: RunSpecEnvelope) -> CompileResponse:
    spec = payload.spec
    _enforce_policy(spec)
    lines = compile_runspec(spec)
    return CompileResponse(cmnd_text="\n".join(lines) + "\n", lines=lines)


@app.post("/runs/create")
def create_run(payload: CreateRunRequest) -> dict:
    spec = payload.spec
    _enforce_policy(spec)

    run_id, status = _create_run_from_spec(spec, auto_enqueue=payload.auto_enqueue)

    return {
        "run_id": run_id,
        "status": status,
        "auto_enqueue": payload.auto_enqueue,
    }


@app.post("/runs/{run_id}/enqueue")
def enqueue_run(run_id: str) -> dict:
    status = run_service.enqueue(run_id)
    return {"run_id": run_id, "status": status}


@app.get("/runs")
def list_runs(
    limit: int = Query(default=20, ge=1, le=200),
    state: str | None = Query(default=None, description="Optional comma-separated state filter"),
) -> dict:
    states: set[str] | None = None
    if state:
        states = {s.strip().upper() for s in state.split(",") if s.strip()}

    runs = store.list_runs(limit=limit, states=states)
    return {"runs": runs, "count": len(runs)}


@app.get("/runs/{run_id}/status")
def run_status(run_id: str) -> dict:
    try:
        return store.get_status(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}") from None


@app.get("/runs/{run_id}/artifacts")
def run_artifacts(run_id: str) -> dict:
    try:
        artifacts = store.get_artifacts(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}") from None
    return {"run_id": run_id, "artifacts": artifacts}


@app.get("/runs/{run_id}/artifacts/{artifact_name}")
def get_artifact(run_id: str, artifact_name: str) -> FileResponse:
    try:
        path = store.get_artifact_path(run_id, artifact_name)
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}") from None
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"artifact not found: {artifact_name}") from None

    return FileResponse(path=path)


def _use_legacy_v1_chat() -> bool:
    return api_mode() == "v1"


@app.post("/chat/sessions")
def create_chat_session(payload: ChatCreateSessionRequest) -> dict:
    if _use_legacy_v1_chat():
        if payload.initial_spec is None:
            session = chat_session_store.create()
        else:
            _enforce_policy(payload.initial_spec)
            session = chat_session_store.create(payload.initial_spec.model_dump())
        return public_session_state(session)

    initial = payload.initial_spec.model_dump() if payload.initial_spec is not None else None
    return legacy_chat_adapter.create_session(initial)


@app.get("/chat/sessions/{session_id}")
def get_chat_session(session_id: str) -> dict:
    if _use_legacy_v1_chat():
        try:
            session = chat_session_store.get(session_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"chat session not found: {session_id}") from None
        return public_session_state(session)

    try:
        return legacy_chat_adapter.get_session(session_id)
    except ThreadNotFoundError:
        raise HTTPException(status_code=404, detail=f"chat session not found: {session_id}") from None


@app.post("/chat/sessions/{session_id}/message")
def chat_message(session_id: str, payload: ChatMessageRequest) -> dict:
    if _use_legacy_v1_chat():
        try:
            result = chat_orchestrator.handle_user_message(session_id, payload.message)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"chat session not found: {session_id}") from None
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        except Exception as exc:  # pylint: disable=broad-except
            raise HTTPException(status_code=500, detail=f"chat failed: {exc}") from None
        return result

    try:
        return legacy_chat_adapter.post_message(session_id, payload.message)
    except ThreadNotFoundError:
        raise HTTPException(status_code=404, detail=f"chat session not found: {session_id}") from None


@app.post("/chat/sessions/{session_id}/apply")
def apply_chat_proposal(session_id: str) -> dict:
    if _use_legacy_v1_chat():
        try:
            session = chat_session_store.get(session_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"chat session not found: {session_id}") from None

        proposed = session.get("proposed_spec")
        if not isinstance(proposed, dict):
            raise HTTPException(status_code=400, detail="no proposed spec to apply")

        try:
            spec_obj = RunSpec.model_validate(proposed)
            _enforce_policy(spec_obj)
        except Exception as exc:  # pylint: disable=broad-except
            raise HTTPException(status_code=400, detail=f"proposed spec invalid: {exc}") from None

        session["working_spec"] = spec_obj.model_dump()
        session["proposed_spec"] = None
        session.setdefault("messages", []).append(
            {"role": "system", "content": "Applied proposed spec to working spec.", "at": _now_iso()}
        )
        chat_session_store.save(session)
        return {"applied": True, "session": public_session_state(session)}

    try:
        return legacy_chat_adapter.apply(session_id)
    except ThreadNotFoundError:
        raise HTTPException(status_code=404, detail=f"chat session not found: {session_id}") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.post("/chat/sessions/{session_id}/run")
def run_from_chat(session_id: str, payload: ChatRunRequest) -> dict:
    if _use_legacy_v1_chat():
        try:
            session = chat_session_store.get(session_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"chat session not found: {session_id}") from None

        source = payload.source
        if source == "proposed":
            spec_payload = session.get("proposed_spec")
            if not isinstance(spec_payload, dict):
                raise HTTPException(status_code=400, detail="no proposed spec to run") from None
        else:
            spec_payload = session.get("working_spec")

        try:
            spec_obj = RunSpec.model_validate(spec_payload)
            _enforce_policy(spec_obj)
        except Exception as exc:  # pylint: disable=broad-except
            raise HTTPException(status_code=400, detail=f"invalid run spec from chat state: {exc}") from None

        run_id, status = _create_run_from_spec(spec_obj, auto_enqueue=True)

        if source == "proposed":
            session["working_spec"] = spec_obj.model_dump()
            session["proposed_spec"] = None
        session["last_run_id"] = run_id
        session.setdefault("messages", []).append(
            {"role": "system", "content": f"Started run {run_id} from {source} spec.", "at": _now_iso()}
        )
        chat_session_store.save(session)

        return {
            "run_id": run_id,
            "status": status,
            "session": public_session_state(session),
        }

    try:
        thread = v2_thread_service.get_thread(session_id)
    except ThreadNotFoundError:
        raise HTTPException(status_code=404, detail=f"chat session not found: {session_id}") from None

    if thread.setting is None:
        raise HTTPException(status_code=400, detail="no active setting")

    spec_obj = RunSpec.model_validate(thread.setting.runspec)
    _enforce_policy(spec_obj)
    run_id, status = _create_run_from_spec(spec_obj, auto_enqueue=True)

    return {
        "run_id": run_id,
        "status": status,
        "session": legacy_chat_adapter.get_session(session_id),
    }


# -------------------------
# v2 Agent + Workflow APIs
# -------------------------


@app.post("/v2/threads", response_model=ThreadResponse)
def v2_create_thread(payload: ThreadCreateRequest) -> ThreadResponse:
    initial = payload.initial_spec.model_dump() if payload.initial_spec is not None else None
    return v2_thread_service.create_thread(initial)


@app.get("/v2/threads/{thread_id}", response_model=ThreadResponse)
def v2_get_thread(thread_id: str) -> ThreadResponse:
    try:
        return v2_thread_service.get_thread(thread_id)
    except ThreadNotFoundError:
        raise HTTPException(status_code=404, detail=f"thread not found: {thread_id}") from None


@app.post("/v2/threads/{thread_id}/messages", response_model=ThreadMessageResponse)
def v2_post_message(thread_id: str, payload: MessageCreateRequest) -> ThreadMessageResponse:
    try:
        return v2_thread_service.post_message(thread_id, payload.message)
    except ThreadNotFoundError:
        raise HTTPException(status_code=404, detail=f"thread not found: {thread_id}") from None


@app.get("/v2/settings/{setting_id}", response_model=SettingResponse)
def v2_get_setting(setting_id: str) -> SettingResponse:
    try:
        return v2_thread_service.get_setting(setting_id)
    except V2SettingNotFoundError:
        raise HTTPException(status_code=404, detail=f"setting not found: {setting_id}") from None


@app.post("/v2/settings/{setting_id}/lock", response_model=SettingLockResponse)
def v2_lock_setting(setting_id: str) -> SettingLockResponse:
    try:
        setting = v2_thread_service.lock_setting(setting_id)
    except V2SettingNotFoundError:
        raise HTTPException(status_code=404, detail=f"setting not found: {setting_id}") from None
    return SettingLockResponse(setting=setting)


@app.post("/v2/workflows", response_model=WorkflowResponse)
def v2_create_workflow(payload: WorkflowCreateRequest) -> WorkflowResponse:
    try:
        return v2_workflow_service.create_workflow(
            setting_id=payload.setting_id,
            name=payload.name,
            schema_version=payload.schema_version,
            graph=payload.graph.model_dump(),
        )
    except WorkflowSettingNotFoundError:
        raise HTTPException(status_code=404, detail=f"setting not found: {payload.setting_id}") from None


@app.get("/v2/workflows/{workflow_id}", response_model=WorkflowResponse)
def v2_get_workflow(workflow_id: str) -> WorkflowResponse:
    try:
        return v2_workflow_service.get_workflow(workflow_id)
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail=f"workflow not found: {workflow_id}") from None


@app.post("/v2/workflows/{workflow_id}/validate", response_model=WorkflowValidationResponse)
def v2_validate_workflow(workflow_id: str) -> WorkflowValidationResponse:
    try:
        errors = v2_workflow_service.validate_workflow(workflow_id)
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail=f"workflow not found: {workflow_id}") from None
    return WorkflowValidationResponse(valid=not errors, errors=errors)


@app.post("/v2/workflows/{workflow_id}/runs", response_model=WorkflowRunResponse)
def v2_start_workflow_run(workflow_id: str, payload: WorkflowRunCreateRequest) -> WorkflowRunResponse:
    try:
        return v2_workflow_service.start_workflow_run(workflow_id, payload.timeout_seconds)
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail=f"workflow not found: {workflow_id}") from None


@app.get("/v2/workflow-runs/{workflow_run_id}", response_model=WorkflowRunResponse)
def v2_get_workflow_run(workflow_run_id: str) -> WorkflowRunResponse:
    try:
        return v2_workflow_service.get_workflow_run(workflow_run_id)
    except WorkflowRunNotFoundError:
        raise HTTPException(status_code=404, detail=f"workflow run not found: {workflow_run_id}") from None


@app.get("/v2/workflow-runs/{workflow_run_id}/artifacts/{name}")
def v2_get_workflow_artifact(workflow_run_id: str, name: str) -> FileResponse:
    try:
        path = v2_workflow_service.get_artifact_path(workflow_run_id, name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"artifact not found: {name}") from None
    return FileResponse(path=path)


@app.exception_handler(ValidationError)
async def validation_exception_handler(_request, exc: ValidationError):
    return _json_error(422, "Validation failed", details=exc.errors())


@app.exception_handler(PolicyViolation)
async def policy_exception_handler(_request, exc: PolicyViolation):
    return _json_error(400, "Policy violation", details=str(exc))


def _enforce_policy(spec: RunSpec) -> None:
    validate_policy(spec)


def _create_run_from_spec(spec: RunSpec, auto_enqueue: bool = True) -> tuple[str, dict]:
    cmnd_text = compile_runspec_to_text(spec)

    metadata = {
        "api_version": app.version,
        "repo_root": str(REPO_ROOT),
        "pythia_config": str(REPO_ROOT / "bin" / "pythia8-config"),
        "pythia_library": str(REPO_ROOT / "lib" / "libpythia8.dylib"),
        "api_mode": api_mode(),
    }

    run_id = store.create_run(spec.model_dump(), cmnd_text, metadata)
    status = store.get_status(run_id)

    if auto_enqueue:
        status = run_service.enqueue(run_id)
    return run_id, status


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _json_error(status_code: int, message: str, details):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status_code, content={"error": message, "details": details})

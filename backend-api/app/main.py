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

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
RUNS_DIR = BACKEND_ROOT / "data" / "runs"
CHAT_SESSIONS_DIR = BACKEND_ROOT / "data" / "chat_sessions"

app = FastAPI(title="PYTHIA Backend API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8765",
        "http://localhost:8765",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = RunStore(RUNS_DIR)
run_service = RunService(store=store, repo_root=REPO_ROOT, backend_root=BACKEND_ROOT)
chat_session_store = ChatSessionStore(CHAT_SESSIONS_DIR)
chat_orchestrator = ChatOrchestrator(chat_session_store)


@app.on_event("startup")
def startup_event() -> None:
    run_service.start()


@app.on_event("shutdown")
def shutdown_event() -> None:
    run_service.stop()


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "PYTHIA Backend API", "status": "ok"}


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


@app.post("/chat/sessions")
def create_chat_session(payload: ChatCreateSessionRequest) -> dict:
    if payload.initial_spec is None:
        session = chat_session_store.create()
    else:
        _enforce_policy(payload.initial_spec)
        session = chat_session_store.create(payload.initial_spec.model_dump())
    return public_session_state(session)


@app.get("/chat/sessions/{session_id}")
def get_chat_session(session_id: str) -> dict:
    try:
        session = chat_session_store.get(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"chat session not found: {session_id}") from None
    return public_session_state(session)


@app.post("/chat/sessions/{session_id}/message")
def chat_message(session_id: str, payload: ChatMessageRequest) -> dict:
    try:
        result = chat_orchestrator.handle_user_message(session_id, payload.message)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"chat session not found: {session_id}") from None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=500, detail=f"chat failed: {exc}") from None

    return result


@app.post("/chat/sessions/{session_id}/apply")
def apply_chat_proposal(session_id: str) -> dict:
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


@app.post("/chat/sessions/{session_id}/run")
def run_from_chat(session_id: str, payload: ChatRunRequest) -> dict:
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

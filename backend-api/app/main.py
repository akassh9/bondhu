from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.params import Query
from fastapi.responses import FileResponse
from pydantic import ValidationError

from .compiler import compile_runspec, compile_runspec_to_text
from .models import CompileResponse, CreateRunRequest, RunSpec, RunSpecEnvelope
from .policy import PolicyViolation, validate_policy
from .run_service import RunService
from .store import RunNotFoundError, RunStore

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
RUNS_DIR = BACKEND_ROOT / "data" / "runs"

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

    cmnd_text = compile_runspec_to_text(spec)

    metadata = {
        "api_version": app.version,
        "repo_root": str(REPO_ROOT),
        "pythia_config": str(REPO_ROOT / "bin" / "pythia8-config"),
        "pythia_library": str(REPO_ROOT / "lib" / "libpythia8.dylib"),
    }

    run_id = store.create_run(spec.model_dump(), cmnd_text, metadata)
    status = store.get_status(run_id)

    if payload.auto_enqueue:
        status = run_service.enqueue(run_id)

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


@app.exception_handler(ValidationError)
async def validation_exception_handler(_request, exc: ValidationError):
    return _json_error(422, "Validation failed", details=exc.errors())


@app.exception_handler(PolicyViolation)
async def policy_exception_handler(_request, exc: PolicyViolation):
    return _json_error(400, "Policy violation", details=str(exc))


def _enforce_policy(spec: RunSpec) -> None:
    validate_policy(spec)


def _json_error(status_code: int, message: str, details):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status_code, content={"error": message, "details": details})

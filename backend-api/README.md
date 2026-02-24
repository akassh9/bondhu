# backend-api

FastAPI backend for typed PYTHIA run orchestration.

## What this provides

- Canonical typed `RunSpec` schema (`app/models.py`)
- Validation + guardrails (`app/policy.py`)
- Deterministic compiler `RunSpec -> run.cmnd` (`app/compiler.py`)
- Local queue + worker with persisted provenance (`app/run_service.py`, `app/store.py`)
- Chat orchestration using OpenAI Responses API (`app/chat_service.py`)
- v2 agentic thread/settings/workflow orchestration (`app/v2/`)
- Endpoints for validate/compile/create/enqueue/status/artifacts
- Real execution using a tiny C++ runner (`runner/pythia_runner.cc`)

## Data location

Runs are persisted under:

- `backend-api/data/runs/<run_id>/`

Each run folder contains:

- `run_spec.json`
- `run.cmnd`
- `status.json`
- `metadata.json`
- `execution.json`
- `stdout.log`
- `stderr.log`
- `event_summary.json` (when generated)
- `analysis_yield_table.json` (auto-generated on success)
- `analysis_cutflow.csv` (auto-generated on success)
- `analysis_histogram.csv` (auto-generated on success)
- `analysis_report.md` (auto-generated on success)
- `diagnostics.json` (parsed PYTHIA error/warning statistics)
- `teammate_summary.json` (human-friendly viability summary + suggestions)
- `llm_run_summary.json` (optional LLM TLDR if key/config available)

## Install and run

From repo root:

```bash
python3 -m venv backend-api/.venv
source backend-api/.venv/bin/activate
pip install -r backend-api/requirements.txt
uvicorn app.main:app --app-dir backend-api --host 127.0.0.1 --port 8000
```

## API endpoints

- `GET /health`
- `GET /runspec/schema`
- `POST /runspec/validate`
- `POST /runspec/compile`
- `POST /runs/create`
- `POST /runs/{run_id}/enqueue`
- `GET /runs`
- `GET /runs/{run_id}/status`
- `GET /runs/{run_id}/artifacts`
- `GET /runs/{run_id}/artifacts/{artifact_name}`
- `POST /chat/sessions`
- `GET /chat/sessions/{session_id}`
- `POST /chat/sessions/{session_id}/message`
- `POST /chat/sessions/{session_id}/apply`
- `POST /chat/sessions/{session_id}/run`
- `POST /v2/threads`
- `GET /v2/threads/{thread_id}`
- `POST /v2/threads/{thread_id}/messages`
- `GET /v2/settings/{setting_id}`
- `POST /v2/settings/{setting_id}/lock`
- `POST /v2/workflows`
- `GET /v2/workflows/{workflow_id}`
- `POST /v2/workflows/{workflow_id}/validate`
- `POST /v2/workflows/{workflow_id}/runs`
- `GET /v2/workflow-runs/{workflow_run_id}`
- `GET /v2/workflow-runs/{workflow_run_id}/artifacts/{name}`

## LLM configuration

Set these before starting the API:

```bash
export OPENAI_API_KEY=\"your_key_here\"
export PYTHIA_LLM_MODEL=\"gpt-5-codex\"   # optional, default gpt-5-codex
export PYTHIA_ENABLE_LLM_RUN_SUMMARY=\"1\"   # optional, default 1
export PYTHIA_API_MODE=\"dual\"              # optional: v1, v2, dual
export PYTHIA_AGENT_MODEL=\"gpt-5-codex\"    # optional override for v2 agent runtime
export PYTHIA_SQLITE_PATH=\"/abs/path/pythia_v2.sqlite3\"  # optional override
```

System prompt source for chat orchestration:

- `backend-api/prompts/chat_system.md`

## v2 migration utility

Import legacy JSON chat sessions into SQLite:

```bash
python backend-api/scripts/migrate_chat_sessions_to_sqlite.py
```

## Schema export

```bash
python backend-api/scripts/export_schema.py
```

Writes:

- `backend-api/schema/runspec.schema.json`

## Smoke test

Start the API, then in another shell:

```bash
python backend-api/scripts/smoke_test.py
```

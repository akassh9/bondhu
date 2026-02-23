# backend-api

FastAPI backend for typed PYTHIA run orchestration.

## What this provides

- Canonical typed `RunSpec` schema (`app/models.py`)
- Validation + guardrails (`app/policy.py`)
- Deterministic compiler `RunSpec -> run.cmnd` (`app/compiler.py`)
- Local queue + worker with persisted provenance (`app/run_service.py`, `app/store.py`)
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

# Pythia Teammate Frontend Prototype

Frontend prototype for configuring PYTHIA runs with structured controls + free-form AI workflow surfaces, now wired to the local backend API.

## Open locally

From this repository root:

```bash
cd /Users/akash009/pythia/pythia8310/frontend-prototype
python3 -m http.server 8765
```

Then open:

- http://localhost:8765
- http://localhost:8765/chat/

## Connect to backend API

Start the API from repo root in a second terminal:

```bash
source backend-api/.venv/bin/activate
uvicorn app.main:app --app-dir backend-api --host 127.0.0.1 --port 8000
```

Then click `Approve Current Spec` and `Run on Backend` in the frontend to submit and monitor a real run.

## MVP features now wired

- Approval gate: form changes require explicit re-approval before execution
- Run history panel: browse recent runs and load status/artifacts
- Real run output: status polling + artifact links from backend
- Chat-first page at `/chat/`: session-based LLM workflow, proposed spec apply, run-from-chat
- Teammate run summary: backend parses PYTHIA logs and returns TLDR + viability flags + suggestions

## Included views

- Run setup, beam/collider, process cards, phase-space cuts
- Event-stage and shower/MPI/tune controls
- PDF/photon settings
- Particle/decay override editor
- Merging/matching advanced section
- Expert raw-overrides textarea
- Live generated PYTHIA settings preview
- Mock run summary and research chat
- Paper attachment list (local file names only)

# frontend-app

React/Vite v2 UI for the agentic flow:

- `/app/chat`
- `/app/settings/:setting_id/review`
- `/app/workflows/:workflow_id`
- `/app/results/:workflow_run_id`

## Run locally

```bash
cd frontend-app
npm install
npm run dev
```

Set backend base URL via localStorage if needed:

```js
localStorage.setItem("PYTHIA_API_BASE", "http://127.0.0.1:8000")
```

Backend API must be running from `backend-api`.

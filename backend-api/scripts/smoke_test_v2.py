#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
import urllib.request

BASE = os.getenv("PYTHIA_API_BASE", "http://127.0.0.1:8000").rstrip("/")


def request(method: str, path: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=body,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    thread = request("POST", "/v2/threads", {})
    thread_id = thread["id"]
    print(f"thread={thread_id}")

    msg = request("POST", f"/v2/threads/{thread_id}/messages", {"message": "soft qcd inelastic at 13 tev with 5000 events"})
    print(f"thread_state={msg['setting_state']}")

    setting_id = msg["thread"]["setting"]["id"]
    request("POST", f"/v2/settings/{setting_id}/lock", {})

    graph = {
        "nodes": [
            {"id": "settings", "type": "settings_source", "config": {}},
            {"id": "mu", "type": "particle_filter", "config": {"pdg": [13, -13], "final_only": True}},
            {"id": "hist", "type": "histogram_1d", "config": {"field": "pt", "bins": 20, "min": 0, "max": 10}},
            {"id": "exp", "type": "export", "config": {"format": "json"}},
        ],
        "edges": [
            {"source": "settings", "target": "mu"},
            {"source": "mu", "target": "hist"},
            {"source": "hist", "target": "exp"},
        ],
    }

    wf = request(
        "POST",
        "/v2/workflows",
        {
            "setting_id": setting_id,
            "name": "smoke workflow",
            "schema_version": "1.0",
            "graph": graph,
        },
    )
    workflow_id = wf["id"]
    print(f"workflow={workflow_id}")

    validation = request("POST", f"/v2/workflows/{workflow_id}/validate", {})
    print(f"valid={validation['valid']}")

    run = request("POST", f"/v2/workflows/{workflow_id}/runs", {"timeout_seconds": 1200})
    workflow_run_id = run["id"]
    print(f"workflow_run={workflow_run_id}")

    deadline = time.time() + 600
    while True:
        status = request("GET", f"/v2/workflow-runs/{workflow_run_id}")
        print(status["state"])
        if status["state"] in {"SUCCEEDED", "FAILED"}:
            print(json.dumps(status, indent=2))
            break
        if time.time() > deadline:
            raise TimeoutError("workflow run timeout")
        time.sleep(1.5)


if __name__ == "__main__":
    main()

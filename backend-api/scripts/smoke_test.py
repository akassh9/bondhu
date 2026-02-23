#!/usr/bin/env python3
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"


SPEC = {
    "schema_version": "1.0",
    "events": 200,
    "times_allow_errors": 10,
    "seed_enabled": True,
    "seed": 8310,
    "beam": {
        "frame_type": 1,
        "id_a": 2212,
        "id_b": 2212,
        "e_cm": 13000
    },
    "processes": ["SoftQCD:inelastic"],
    "phase_space": {
        "p_that_min": 20
    },
    "event_stages": {
        "process_level_all": True,
        "mpi": True,
        "isr": True,
        "fsr": True,
        "hadron_all": True,
        "hadronize": True,
        "decay": True
    },
    "shower_mpi_tune": {
        "space_ptmax_match": 1,
        "time_ptmax_match": 1,
        "mpi_pt0_ref": 2.3,
        "mpi_b_profile": 2,
        "tune_pp": 14,
        "tune_ee": 7
    },
    "pdf_photon": {
        "p_set": 14,
        "lepton": False,
        "beam_a2gamma": False,
        "beam_b2gamma": False,
        "use_hard": False,
        "photon_parton_all": False
    },
    "pdg_overrides": [
        {"pdg": 221, "key": "onMode", "value": "off"},
        {"pdg": 221, "key": "addChannel", "value": "1 1.0 0 13 -13 13 -13"}
    ],
    "expert_overrides": [],
    "merging": {"enabled": False, "process": "pp>jj", "tms": 30, "n_jet_max": 2},
    "jet_matching": {"enabled": False, "q_cut": 30}
}


def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    print("Creating run...")
    created = post("/runs/create", {"spec": SPEC, "auto_enqueue": True})
    run_id = created["run_id"]
    print(f"Run ID: {run_id}")

    deadline = time.time() + 180
    while True:
        status = get(f"/runs/{run_id}/status")
        state = status["state"]
        print(f"state={state}")
        if state in {"SUCCEEDED", "FAILED"}:
            break
        if time.time() > deadline:
            raise TimeoutError("run did not finish before deadline")
        time.sleep(1.5)

    artifacts = get(f"/runs/{run_id}/artifacts")
    print("Artifacts:")
    for artifact in artifacts["artifacts"]:
        print(f"- {artifact['name']} ({artifact['size_bytes']} bytes)")

    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code}: {body}")

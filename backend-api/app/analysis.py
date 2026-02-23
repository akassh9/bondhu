from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def generate_basic_analysis(run_dir: Path, spec: dict[str, Any], event_summary: dict[str, Any] | None) -> dict[str, Any]:
    event_summary = event_summary or {}

    requested = _safe_int(spec.get("events"), 0)
    attempted = _safe_int(event_summary.get("attempted_events"), requested)
    accepted = _safe_int(event_summary.get("accepted_events"), 0)
    failed = _safe_int(event_summary.get("failed_events"), max(0, attempted - accepted))

    acceptance_attempted = (accepted / attempted) if attempted > 0 else 0.0
    acceptance_requested = (accepted / requested) if requested > 0 else 0.0

    artifacts: list[str] = []

    yield_payload = {
        "generated_at": _now_iso(),
        "requested_events": requested,
        "attempted_events": attempted,
        "accepted_events": accepted,
        "failed_events": failed,
        "acceptance_vs_attempted": round(acceptance_attempted, 6),
        "acceptance_vs_requested": round(acceptance_requested, 6),
        "notes": [
            "Auto-generated MVP analysis from run-level counters.",
            "No detector/reco-level selection applied in this plugin.",
        ],
    }
    yield_path = run_dir / "analysis_yield_table.json"
    yield_path.write_text(json.dumps(yield_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    artifacts.append(yield_path.name)

    cutflow_path = run_dir / "analysis_cutflow.csv"
    with cutflow_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["step", "count"])
        writer.writerow(["Requested", requested])
        writer.writerow(["Attempted", attempted])
        writer.writerow(["Accepted", accepted])
        writer.writerow(["Failed", failed])
    artifacts.append(cutflow_path.name)

    hist_path = run_dir / "analysis_histogram.csv"
    with hist_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["bin", "count"])
        writer.writerow(["accepted", accepted])
        writer.writerow(["failed", failed])
    artifacts.append(hist_path.name)

    report_path = run_dir / "analysis_report.md"
    report_path.write_text(
        "\n".join(
            [
                "# Analysis Report (MVP)",
                "",
                f"- Generated at: {_now_iso()}",
                f"- Requested events: {requested}",
                f"- Attempted events: {attempted}",
                f"- Accepted events: {accepted}",
                f"- Failed events: {failed}",
                f"- Acceptance (accepted/attempted): {acceptance_attempted:.6f}",
                f"- Acceptance (accepted/requested): {acceptance_requested:.6f}",
                "",
                "## Notes",
                "- This is an MVP generator-level analysis plugin.",
                "- Histogram export is a minimal placeholder until event-level histogramming is added.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    artifacts.append(report_path.name)

    return {
        "plugin": "basic_mvp_analysis",
        "generated_at": _now_iso(),
        "artifacts": artifacts,
        "accepted_events": accepted,
        "failed_events": failed,
        "acceptance_vs_attempted": round(acceptance_attempted, 6),
    }

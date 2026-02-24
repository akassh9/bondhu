from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .workflow_validation import topological_order


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_particles(tracked_csv: Path) -> list[dict[str, Any]]:
    if not tracked_csv.exists():
        return []

    rows: list[dict[str, Any]] = []
    with tracked_csv.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(
                {
                    "event_id": _to_int(row.get("event_id")),
                    "particle_index": _to_int(row.get("particle_index")),
                    "pdg": _to_int(row.get("pdg")),
                    "charge": _to_float(row.get("charge")),
                    "pt": _to_float(row.get("pt")),
                    "eta": _to_float(row.get("eta")),
                    "phi": _to_float(row.get("phi")),
                    "mass": _to_float(row.get("mass")),
                    "energy": _to_float(row.get("energy")),
                    "is_final": str(row.get("is_final", "1")).strip() in {"1", "true", "True"},
                }
            )
    return rows


def _apply_particle_filter(rows: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    pdgs = {int(v) for v in config.get("pdg", []) if isinstance(v, (int, float, str)) and str(v).strip()}
    charge = config.get("charge")
    final_only = bool(config.get("final_only", True))

    out: list[dict[str, Any]] = []
    for row in rows:
        if pdgs and row["pdg"] not in pdgs:
            continue
        if charge is not None:
            if int(math.copysign(1, row["charge"])) != int(math.copysign(1, float(charge))):
                continue
        if final_only and not row["is_final"]:
            continue
        out.append(row)
    return out


def _apply_kinematic_cut(rows: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    pt_min = _to_float(config.get("pt_min"), float("-inf"))
    pt_max = _to_float(config.get("pt_max"), float("inf"))
    eta_min = _to_float(config.get("eta_min"), float("-inf"))
    eta_max = _to_float(config.get("eta_max"), float("inf"))
    phi_min = _to_float(config.get("phi_min"), float("-inf"))
    phi_max = _to_float(config.get("phi_max"), float("inf"))
    mass_min = _to_float(config.get("mass_min"), float("-inf"))
    mass_max = _to_float(config.get("mass_max"), float("inf"))

    out = []
    for row in rows:
        if not (pt_min <= row["pt"] <= pt_max):
            continue
        if not (eta_min <= row["eta"] <= eta_max):
            continue
        if not (phi_min <= row["phi"] <= phi_max):
            continue
        if not (mass_min <= row["mass"] <= mass_max):
            continue
        out.append(row)
    return out


def _apply_event_selection(rows: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    min_particles = _to_int(config.get("min_particles"), 1)
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["event_id"]].append(row)

    keep_events = {event_id for event_id, values in grouped.items() if len(values) >= min_particles}
    return [row for row in rows if row["event_id"] in keep_events]


def _histogram_1d(rows: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    field = str(config.get("field", "pt"))
    bins = max(1, _to_int(config.get("bins"), 20))
    vmin = _to_float(config.get("min"), 0.0)
    vmax = _to_float(config.get("max"), 1.0)
    width = (vmax - vmin) / bins if bins > 0 else 1.0

    counts = [0 for _ in range(bins)]
    for row in rows:
        value = _to_float(row.get(field), float("nan"))
        if math.isnan(value) or value < vmin or value > vmax:
            continue
        idx = bins - 1 if value == vmax else int((value - vmin) / width)
        if 0 <= idx < bins:
            counts[idx] += 1

    return {
        "field": field,
        "bins": bins,
        "min": vmin,
        "max": vmax,
        "counts": counts,
    }


def _histogram_2d(rows: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    x_field = str(config.get("x_field", "pt"))
    y_field = str(config.get("y_field", "eta"))
    x_bins = max(1, _to_int(config.get("x_bins"), 20))
    y_bins = max(1, _to_int(config.get("y_bins"), 20))
    x_min = _to_float(config.get("x_min"), 0.0)
    x_max = _to_float(config.get("x_max"), 1.0)
    y_min = _to_float(config.get("y_min"), -1.0)
    y_max = _to_float(config.get("y_max"), 1.0)
    x_w = (x_max - x_min) / x_bins
    y_w = (y_max - y_min) / y_bins

    grid = [[0 for _ in range(y_bins)] for _ in range(x_bins)]
    for row in rows:
        x = _to_float(row.get(x_field), float("nan"))
        y = _to_float(row.get(y_field), float("nan"))
        if math.isnan(x) or math.isnan(y):
            continue
        if not (x_min <= x <= x_max and y_min <= y <= y_max):
            continue
        ix = x_bins - 1 if x == x_max else int((x - x_min) / x_w)
        iy = y_bins - 1 if y == y_max else int((y - y_min) / y_w)
        if 0 <= ix < x_bins and 0 <= iy < y_bins:
            grid[ix][iy] += 1

    return {
        "x_field": x_field,
        "y_field": y_field,
        "x_bins": x_bins,
        "y_bins": y_bins,
        "x_min": x_min,
        "x_max": x_max,
        "y_min": y_min,
        "y_max": y_max,
        "counts": grid,
    }


def _cutflow(rows: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    cuts = config.get("cuts")
    if not isinstance(cuts, list):
        cuts = []

    current = list(rows)
    out_steps = [{"name": "input", "count": len(current)}]

    for idx, cut in enumerate(cuts):
        if not isinstance(cut, dict):
            continue
        field = str(cut.get("field", "pt"))
        op = str(cut.get("op", ">="))
        value = _to_float(cut.get("value"), 0.0)

        filtered: list[dict[str, Any]] = []
        for row in current:
            v = _to_float(row.get(field), float("nan"))
            if math.isnan(v):
                continue
            keep = False
            if op == ">":
                keep = v > value
            elif op == ">=":
                keep = v >= value
            elif op == "<":
                keep = v < value
            elif op == "<=":
                keep = v <= value
            elif op == "==":
                keep = v == value
            if keep:
                filtered.append(row)

        current = filtered
        out_steps.append({"name": cut.get("name") or f"cut_{idx + 1}", "count": len(current)})

    return {"steps": out_steps}


def _yield_estimator(summary: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    accepted = _to_int(summary.get("accepted_events"), 0)
    sigma_mb = _to_float(config.get("sigma_mb"), 0.0)
    lumi_fb = _to_float(config.get("lumi_fb"), 0.0)
    br = _to_float(config.get("branching_ratio"), 1.0)

    # 1 mb * 1 fb^-1 = 1e12 events
    expected = sigma_mb * lumi_fb * 1.0e12 * br
    efficiency = _to_float(summary.get("accepted_events"), 0.0) / max(_to_float(summary.get("attempted_events"), 1.0), 1.0)
    observed = expected * efficiency

    return {
        "accepted_events": accepted,
        "sigma_mb": sigma_mb,
        "lumi_fb": lumi_fb,
        "branching_ratio": br,
        "expected_events": expected,
        "efficiency": efficiency,
        "observed_events": observed,
    }


def _write_export(
    artifact_dir: Path,
    node_id: str,
    config: dict[str, Any],
    payload: dict[str, Any],
) -> list[str]:
    fmt = str(config.get("format", "json")).lower()
    written: list[str] = []
    if fmt in {"json", "all"}:
        name = f"{node_id}.json"
        (artifact_dir / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(name)

    if fmt in {"csv", "all"}:
        name = f"{node_id}.csv"
        flat_rows = payload.get("steps") if isinstance(payload, dict) and isinstance(payload.get("steps"), list) else None
        with (artifact_dir / name).open("w", newline="", encoding="utf-8") as handle:
            if flat_rows:
                writer = csv.DictWriter(handle, fieldnames=sorted({k for row in flat_rows for k in row.keys()}))
                writer.writeheader()
                writer.writerows(flat_rows)
            else:
                writer = csv.writer(handle)
                writer.writerow(["key", "value"])
                for key, value in payload.items() if isinstance(payload, dict) else []:
                    writer.writerow([key, json.dumps(value)])
        written.append(name)

    return written


def execute_workflow(
    *,
    graph: dict[str, Any],
    tracked_particles_csv: Path,
    event_summary_path: Path,
    artifact_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    artifact_dir.mkdir(parents=True, exist_ok=True)

    particles = load_particles(tracked_particles_csv)
    event_summary = {}
    if event_summary_path.exists():
        event_summary = json.loads(event_summary_path.read_text(encoding="utf-8"))

    nodes = {str(node["id"]): node for node in graph.get("nodes", [])}
    order = topological_order(graph)

    outputs: dict[str, Any] = {}
    node_results: list[dict[str, Any]] = []
    current_rows = particles

    for node_id in order:
        node = nodes[node_id]
        node_type = str(node.get("type"))
        config = node.get("config") or {}
        source_rows = current_rows

        artifacts: list[str] = []
        output: dict[str, Any]

        if node_type == "settings_source":
            current_rows = particles
            output = {"row_count": len(current_rows), "event_summary": event_summary}
        elif node_type == "particle_filter":
            rows = _apply_particle_filter(source_rows, config)
            current_rows = rows
            output = {"count": len(rows)}
        elif node_type == "kinematic_cut":
            rows = _apply_kinematic_cut(source_rows, config)
            current_rows = rows
            output = {"count": len(rows)}
        elif node_type == "event_selection":
            rows = _apply_event_selection(source_rows, config)
            current_rows = rows
            output = {"count": len(rows)}
        elif node_type == "histogram_1d":
            hist = _histogram_1d(source_rows, config)
            output = {"histogram_1d": hist}
        elif node_type == "histogram_2d":
            hist2d = _histogram_2d(source_rows, config)
            output = {"histogram_2d": hist2d}
        elif node_type == "cutflow":
            cutflow = _cutflow(source_rows, config)
            output = cutflow
        elif node_type == "yield_estimator":
            output = _yield_estimator(event_summary, config)
        elif node_type == "export":
            upstream = node_results[-1].get("output") if node_results else {}
            payload = upstream if isinstance(upstream, dict) else {"value": upstream}
            artifacts = _write_export(artifact_dir, node_id, config, payload)
            output = {"exported": artifacts}
        else:
            output = {"error": f"unsupported node type {node_type}"}

        outputs[node_id] = output
        node_results.append(
            {
                "node_id": node_id,
                "node_type": node_type,
                "state": "SUCCEEDED",
                "output": output,
                "artifacts": artifacts,
            }
        )

    summary = {
        "nodes_executed": len(node_results),
        "particle_rows": len(particles),
        "event_summary": event_summary,
    }

    return node_results, summary

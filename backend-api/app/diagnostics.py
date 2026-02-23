from __future__ import annotations

import json
import os
import re
from typing import Any

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]

_MESSAGE_STAT_RE = re.compile(r"^\|\s*(\d+)\s+(Error|Warning)\s+in\s+(.+?)\s*\|\s*$")


def parse_message_statistics(stdout_log: str) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for raw_line in stdout_log.splitlines():
        line = raw_line.strip()
        match = _MESSAGE_STAT_RE.match(line)
        if not match:
            continue

        count = int(match.group(1))
        level = match.group(2)
        message = match.group(3).strip()

        item = {"count": count, "message": message}
        if level == "Error":
            errors.append(item)
        else:
            warnings.append(item)

    errors.sort(key=lambda x: x["count"], reverse=True)
    warnings.sort(key=lambda x: x["count"], reverse=True)

    return {
        "total_error_messages": sum(item["count"] for item in errors),
        "total_warning_messages": sum(item["count"] for item in warnings),
        "top_errors": errors[:10],
        "top_warnings": warnings[:10],
    }


def infer_intent(spec: dict[str, Any]) -> str:
    processes = set(spec.get("processes", []))
    pdg_overrides = spec.get("pdg_overrides", [])

    if any(str(ov.get("pdg")) in {"221", "331"} for ov in pdg_overrides):
        return "Meson rare-decay generator-level study"

    if "SoftQCD:inelastic" in processes or "SoftQCD:all" in processes:
        return "Minimum-bias / underlying-event QCD study"
    if "HardQCD:all" in processes:
        return "Hard-scatter jet/QCD production study"
    if "WeakSingleBoson:ffbar2gmZ" in processes or "WeakSingleBoson:ffbar2W" in processes:
        return "Electroweak boson production study"
    if "Top:gg2ttbar" in processes or "Top:qqbar2ttbar" in processes:
        return "Top-pair production study"
    if "HiggsSM:ffbar2HW" in processes:
        return "Higgs associated production study"

    if processes:
        return "Custom process study"
    return "Unspecified simulation study"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def build_teammate_summary(
    spec: dict[str, Any],
    event_summary: dict[str, Any] | None,
    diagnostics: dict[str, Any],
    exit_code: int,
) -> dict[str, Any]:
    event_summary = event_summary or {}

    attempted = _safe_int(event_summary.get("attempted_events"), _safe_int(spec.get("events"), 0))
    accepted = _safe_int(event_summary.get("accepted_events"), 0)
    failed = _safe_int(event_summary.get("failed_events"), max(0, attempted - accepted))

    error_msgs = _safe_int(diagnostics.get("total_error_messages"), 0)
    warning_msgs = _safe_int(diagnostics.get("total_warning_messages"), 0)

    flags: list[str] = []
    suggestions: list[str] = []

    viability = "good"
    if exit_code != 0:
        viability = "non_viable"
        flags.append(f"Runner exit code is {exit_code}.")
    if attempted > 0 and accepted == 0:
        viability = "non_viable"
        flags.append("No events accepted.")

    fail_fraction = (failed / attempted) if attempted > 0 else 0.0
    if viability != "non_viable":
        if fail_fraction > 0.10 or error_msgs > 150:
            viability = "non_viable"
        elif fail_fraction > 0.01 or error_msgs > 0 or warning_msgs > 25:
            viability = "caution"

    if fail_fraction > 0.01:
        flags.append(f"Failed events fraction is {fail_fraction:.2%}.")
    if error_msgs > 0:
        flags.append(f"PYTHIA reported {error_msgs} error-stat messages.")
    if warning_msgs > 25:
        flags.append(f"High warning volume: {warning_msgs} warning-stat messages.")

    top_errors = diagnostics.get("top_errors", [])
    if top_errors:
        suggestions.append("Inspect top error categories in diagnostics before trusting physics conclusions.")
    if warning_msgs > 0:
        suggestions.append("Review warning categories; repeated shower or hadronization warnings can bias tails.")

    if fail_fraction == 0 and error_msgs == 0:
        suggestions.append("Run appears numerically stable; proceed to larger statistics or analysis plugins.")

    intent = infer_intent(spec)
    suggestions.append("Compare at least two nearby seeds to confirm stability of key yields.")

    tldr = (
        f"{intent}: attempted {attempted} events, accepted {accepted}, failed {failed}. "
        f"Viability assessment: {viability}."
    )

    return {
        "tldr": tldr,
        "viability": viability,
        "flags": flags,
        "suggestions": suggestions,
        "inferred_intent": intent,
        "key_stats": {
            "attempted_events": attempted,
            "accepted_events": accepted,
            "failed_events": failed,
            "error_messages": error_msgs,
            "warning_messages": warning_msgs,
            "acceptance": (accepted / attempted) if attempted > 0 else 0.0,
        },
    }


def maybe_generate_llm_summary(
    spec: dict[str, Any],
    teammate_summary: dict[str, Any],
    diagnostics: dict[str, Any],
) -> dict[str, Any] | None:
    enabled = os.getenv("PYTHIA_ENABLE_LLM_RUN_SUMMARY", "1").strip().lower() in {"1", "true", "yes"}
    if not enabled:
        return None

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or OpenAI is None:
        return None

    model = os.getenv("PYTHIA_LLM_MODEL", "gpt-5-codex")

    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model,
            instructions=(
                "You are a concise simulation teammate. "
                "Summarize viability, risks, and next actions from run diagnostics. "
                "Return strict JSON only."
            ),
            input=(
                "RunSpec JSON:\n"
                + json.dumps(spec, indent=2, sort_keys=True)
                + "\n\nHeuristic summary JSON:\n"
                + json.dumps(teammate_summary, indent=2, sort_keys=True)
                + "\n\nDiagnostics JSON:\n"
                + json.dumps(diagnostics, indent=2, sort_keys=True)
            ),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "run_tldr",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "tldr": {"type": "string"},
                            "viability": {
                                "type": "string",
                                "enum": ["good", "caution", "non_viable"],
                            },
                            "risks": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "next_steps": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["tldr", "viability", "risks", "next_steps"],
                    },
                }
            },
        )

        text = getattr(response, "output_text", "")
        if not text:
            payload = response.model_dump() if hasattr(response, "model_dump") else {}
            output = payload.get("output", []) if isinstance(payload, dict) else []
            chunks: list[str] = []
            for item in output:
                if item.get("type") != "message":
                    continue
                for content in item.get("content", []):
                    if content.get("type") == "output_text" and content.get("text"):
                        chunks.append(content["text"])
            text = "\n".join(chunks)

        if not text:
            return None

        parsed = json.loads(text)
        parsed["model"] = model
        return parsed
    except Exception:
        return None

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency for agent runtime
    import agents  # type: ignore
except Exception:  # pragma: no cover
    agents = None  # type: ignore


@dataclass
class AgentTurnResult:
    assistant_message: str
    proposal_summary: str
    proposed_spec_patch: dict[str, Any]
    workflow_intent: dict[str, Any]
    setting_state: str
    run_recommended: bool
    trace_id: str | None
    response_id: str | None


class AgentRuntime:
    """Wrapper that prefers Agents SDK if available, with Responses fallback."""

    def __init__(self, model: str) -> None:
        self.model = model

    @staticmethod
    def _schema() -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "assistant_message": {"type": "string"},
                "proposal_summary": {"type": "string"},
                "proposed_spec_json": {"type": "string"},
                "workflow_intent": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "summary": {"type": "string"},
                        "needs_workflow_stage": {"type": "boolean"},
                        "particle_filter": {
                            "type": ["object", "null"],
                            "additionalProperties": False,
                            "properties": {
                                "pdg": {"type": "array", "items": {"type": "integer"}},
                                "final_only": {"type": "boolean"},
                            },
                            "required": ["pdg", "final_only"],
                        },
                        "kinematic_cut": {
                            "type": ["object", "null"],
                            "additionalProperties": False,
                            "properties": {
                                "pt_min": {"type": ["number", "null"]},
                                "pt_max": {"type": ["number", "null"]},
                                "eta_min": {"type": ["number", "null"]},
                                "eta_max": {"type": ["number", "null"]},
                                "phi_min": {"type": ["number", "null"]},
                                "phi_max": {"type": ["number", "null"]},
                                "mass_min": {"type": ["number", "null"]},
                                "mass_max": {"type": ["number", "null"]},
                            },
                            "required": [
                                "pt_min",
                                "pt_max",
                                "eta_min",
                                "eta_max",
                                "phi_min",
                                "phi_max",
                                "mass_min",
                                "mass_max",
                            ],
                        },
                        "histogram_1d": {
                            "type": ["object", "null"],
                            "additionalProperties": False,
                            "properties": {
                                "field": {"type": "string"},
                                "bins": {"type": "integer"},
                                "min": {"type": "number"},
                                "max": {"type": "number"},
                            },
                            "required": ["field", "bins", "min", "max"],
                        },
                        "include_cutflow": {"type": "boolean"},
                        "export_formats": {
                            "type": "array",
                            "items": {"type": "string", "enum": ["json", "csv", "png"]},
                        },
                        "unavailable_requests": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": [
                        "summary",
                        "needs_workflow_stage",
                        "particle_filter",
                        "kinematic_cut",
                        "histogram_1d",
                        "include_cutflow",
                        "export_formats",
                        "unavailable_requests",
                    ],
                },
                "setting_state": {
                    "type": "string",
                    "enum": ["DISCOVERY", "SETTING_DRAFT", "SETTING_READY"],
                },
                "run_recommended": {"type": "boolean"},
            },
            "required": [
                "assistant_message",
                "proposal_summary",
                "proposed_spec_json",
                "workflow_intent",
                "setting_state",
                "run_recommended",
            ],
        }

    def run(
        self,
        *,
        system_prompt: str,
        user_message: str,
        working_spec: dict[str, Any],
        previous_response_id: str | None,
    ) -> AgentTurnResult:
        # The SDK import is optional in this repository; fallback path stays robust.
        if agents is not None:
            return self._run_via_responses(system_prompt, user_message, working_spec, previous_response_id)
        return self._run_via_responses(system_prompt, user_message, working_spec, previous_response_id)

    def _run_via_responses(
        self,
        system_prompt: str,
        user_message: str,
        working_spec: dict[str, Any],
        previous_response_id: str | None,
    ) -> AgentTurnResult:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key or OpenAI is None:
            reasons: list[str] = []
            if not api_key:
                reasons.append("OPENAI_API_KEY is not set in the backend process")
            if OpenAI is None:
                reasons.append("openai package is not available")
            reason_text = "; ".join(reasons) if reasons else "LLM client is unavailable"
            return AgentTurnResult(
                assistant_message=(
                    f"I cannot call the LLM right now ({reason_text}). "
                    "Set backend LLM configuration and retry."
                ),
                proposal_summary=f"LLM unavailable: {reason_text}.",
                proposed_spec_patch={},
                workflow_intent={},
                setting_state="DISCOVERY",
                run_recommended=False,
                trace_id=None,
                response_id=None,
            )

        client = OpenAI(api_key=api_key)
        input_text = (
            "User message:\n"
            f"{user_message}\n\n"
            "Current working RunSpec JSON:\n"
            f"{json.dumps(working_spec, indent=2, sort_keys=True)}\n"
        )

        params: dict[str, Any] = {
            "model": self.model,
            "instructions": system_prompt,
            "input": input_text,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "agent_turn",
                    "strict": True,
                    "schema": self._schema(),
                }
            },
            "store": True,
        }
        if previous_response_id:
            params["previous_response_id"] = previous_response_id

        try:
            response = client.responses.create(**params)
            payload_text = getattr(response, "output_text", "")
            if not payload_text:
                data = response.model_dump() if hasattr(response, "model_dump") else {}
                chunks: list[str] = []
                for item in data.get("output", []) if isinstance(data, dict) else []:
                    if item.get("type") != "message":
                        continue
                    for content in item.get("content", []):
                        if content.get("type") == "output_text" and content.get("text"):
                            chunks.append(content["text"])
                payload_text = "\n".join(chunks)

            parsed = json.loads(payload_text)
            patch_text = parsed.get("proposed_spec_json", "{}")
            patch_obj = json.loads(patch_text) if isinstance(patch_text, str) and patch_text.strip() else {}
            if not isinstance(patch_obj, dict):
                patch_obj = {}
            workflow_intent_obj = parsed.get("workflow_intent", {})
            if not isinstance(workflow_intent_obj, dict):
                workflow_intent_obj = {}

            trace_id = None
            if hasattr(response, "id"):
                trace_id = getattr(response, "id")

            return AgentTurnResult(
                assistant_message=str(parsed.get("assistant_message", "")),
                proposal_summary=str(parsed.get("proposal_summary", "")),
                proposed_spec_patch=patch_obj,
                workflow_intent=workflow_intent_obj,
                setting_state=str(parsed.get("setting_state", "DISCOVERY")),
                run_recommended=bool(parsed.get("run_recommended", False)),
                trace_id=trace_id,
                response_id=getattr(response, "id", None),
            )
        except Exception as exc:  # pylint: disable=broad-except
            reason_text = str(exc).strip() or "LLM call failed"
            return AgentTurnResult(
                assistant_message=f"I could not complete the LLM planning call: {reason_text}",
                proposal_summary=f"LLM call failed: {reason_text}",
                proposed_spec_patch={},
                workflow_intent={},
                setting_state="DISCOVERY",
                run_recommended=False,
                trace_id=None,
                response_id=None,
            )

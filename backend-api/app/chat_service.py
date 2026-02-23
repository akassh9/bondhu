from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]

from .compiler import compile_runspec_to_text
from .models import PROCESS_KEYS, RunSpec
from .policy import validate_policy


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _deep_merge(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        out = dict(base)
        for key, value in patch.items():
            out[key] = _deep_merge(base.get(key), value) if key in base else value
        return out
    return patch


def _load_system_prompt() -> str:
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "chat_system.md"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8").strip()
    return (
        "You are a PYTHIA run-planning copilot. "
        "Return structured JSON only. "
        "Always provide proposed_spec_json as a JSON object string (use '{}' for no changes)."
    )


def _sanitize_proposal_patch(patch: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(patch))

    # Inclusive SoftQCD commonly means removing pTHatMin cut;
    # represent this with 0.0 instead of null to satisfy typed schema.
    phase_space = out.get("phase_space")
    if isinstance(phase_space, dict) and phase_space.get("p_that_min") is None:
        phase_space["p_that_min"] = 0.0

    # Drop nulls for top-level required scalar fields if model emits them.
    for key in ("events", "times_allow_errors", "seed", "seed_enabled"):
        if key in out and out[key] is None:
            del out[key]

    return out


def _stable_serialize(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, list):
        return "[" + ",".join(_stable_serialize(v) for v in value) + "]"
    if isinstance(value, dict):
        keys = sorted(value.keys())
        return "{" + ",".join(f"{json.dumps(k)}:{_stable_serialize(value[k])}" for k in keys) + "}"
    return json.dumps(value, sort_keys=True)


def _flatten(value: Any, prefix: str = "", out: dict[str, Any] | None = None) -> dict[str, Any]:
    if out is None:
        out = {}

    if value is None:
        out[prefix or "<root>"] = None
        return out

    if isinstance(value, list):
        out[prefix or "<root>"] = ",".join(_stable_serialize(v) for v in value)
        return out

    if not isinstance(value, dict):
        out[prefix or "<root>"] = value
        return out

    keys = sorted(value.keys())
    if not keys:
        out[prefix or "<root>"] = "{}"
        return out

    for key in keys:
        next_prefix = f"{prefix}.{key}" if prefix else key
        _flatten(value[key], next_prefix, out)

    return out


def spec_diff_lines(old_spec: dict[str, Any] | None, new_spec: dict[str, Any], max_lines: int = 120) -> list[str]:
    if old_spec is None:
        return ["No prior spec."]

    old_flat = _flatten(old_spec)
    new_flat = _flatten(new_spec)
    keys = sorted(set(old_flat.keys()) | set(new_flat.keys()))

    lines: list[str] = []
    for key in keys:
        old_val = old_flat.get(key, "<missing>")
        new_val = new_flat.get(key, "<missing>")

        if key not in old_flat:
            lines.append(f"+ {key}: {new_val}")
            continue
        if key not in new_flat:
            lines.append(f"- {key}: {old_val}")
            continue
        if _stable_serialize(old_val) != _stable_serialize(new_val):
            lines.append(f"~ {key}: {old_val} -> {new_val}")

    if not lines:
        return ["No differences."]

    if len(lines) > max_lines:
        clipped = lines[:max_lines]
        clipped.append(f"... {len(lines) - max_lines} more changes")
        return clipped

    return lines


class ChatSessionStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _session_path(self, session_id: str) -> Path:
        return self.root_dir / f"{session_id}.json"

    def _read(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def create(self, initial_spec: dict[str, Any] | None = None) -> dict[str, Any]:
        session_id = uuid.uuid4().hex[:12]
        path = self._session_path(session_id)

        spec_payload = initial_spec or RunSpec().model_dump()
        now = _now_iso()
        session = {
            "session_id": session_id,
            "created_at": now,
            "updated_at": now,
            "working_spec": spec_payload,
            "proposed_spec": None,
            "messages": [],
            "llm_previous_response_id": None,
            "last_run_id": None,
        }

        with self._lock:
            self._write(path, session)

        return session

    def get(self, session_id: str) -> dict[str, Any]:
        path = self._session_path(session_id)
        if not path.exists():
            raise FileNotFoundError(session_id)
        with self._lock:
            return self._read(path)

    def save(self, session: dict[str, Any]) -> None:
        session["updated_at"] = _now_iso()
        path = self._session_path(session["session_id"])
        with self._lock:
            self._write(path, session)


class ChatOrchestrator:
    def __init__(self, session_store: ChatSessionStore) -> None:
        self.session_store = session_store
        self._system_prompt = _load_system_prompt()

    @staticmethod
    def _model_name() -> str:
        return os.getenv("PYTHIA_LLM_MODEL", "gpt-5-codex")

    def _client(self):
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        if OpenAI is None:
            raise RuntimeError("openai package is not installed")
        return OpenAI(api_key=api_key)

    @staticmethod
    def _extract_output_text(response: Any) -> str:
        text = getattr(response, "output_text", None)
        if text:
            return text

        payload = response.model_dump() if hasattr(response, "model_dump") else response
        if isinstance(payload, dict):
            output = payload.get("output", [])
            chunks: list[str] = []
            for item in output:
                if item.get("type") != "message":
                    continue
                for content in item.get("content", []):
                    if content.get("type") == "output_text" and content.get("text"):
                        chunks.append(content["text"])
            if chunks:
                return "\n".join(chunks)

        raise RuntimeError("No text output from model")

    def _call_llm(self, session: dict[str, Any], user_message: str) -> tuple[dict[str, Any], str]:
        client = self._client()
        model = self._model_name()

        working_spec = session["working_spec"]
        proposed_spec = session.get("proposed_spec")
        process_keys = sorted(PROCESS_KEYS)

        instructions = self._system_prompt

        input_text = (
            "User message:\n"
            f"{user_message}\n\n"
            "Current working RunSpec JSON:\n"
            f"{json.dumps(working_spec, indent=2, sort_keys=True)}\n\n"
            "Current proposed RunSpec JSON (if any):\n"
            f"{json.dumps(proposed_spec, indent=2, sort_keys=True) if proposed_spec else 'null'}\n\n"
            "Allowed process keys:\n"
            + "\n".join(process_keys)
        )

        params: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": input_text,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "pythia_chat_response",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "assistant_message": {"type": "string"},
                            "proposal_summary": {"type": "string"},
                            "proposed_spec_json": {"type": "string"},
                            "run_recommended": {"type": "boolean"},
                        },
                        "required": [
                            "assistant_message",
                            "proposal_summary",
                            "proposed_spec_json",
                            "run_recommended",
                        ],
                    },
                }
            },
            "store": True,
        }

        prev_id = session.get("llm_previous_response_id")
        if prev_id:
            params["previous_response_id"] = prev_id

        response = client.responses.create(**params)
        session["llm_previous_response_id"] = getattr(response, "id", None)

        raw_text = self._extract_output_text(response)
        parsed = json.loads(raw_text)
        return parsed, model

    def handle_user_message(self, session_id: str, user_message: str) -> dict[str, Any]:
        session = self.session_store.get(session_id)

        parsed, model = self._call_llm(session, user_message)

        working = session["working_spec"]
        proposed_json = parsed.get("proposed_spec_json")
        proposed_raw: dict[str, Any] | None = None
        normalized_proposed: dict[str, Any] | None = None
        validation_error: str | None = None
        cmnd_preview: str | None = None
        diff_lines: list[str] = []

        if isinstance(proposed_json, str) and proposed_json.strip():
            try:
                maybe_obj = json.loads(proposed_json)
            except json.JSONDecodeError as exc:
                validation_error = f"assistant proposed_spec_json is not valid JSON: {exc}"
                maybe_obj = None
            if isinstance(maybe_obj, dict):
                proposed_raw = maybe_obj
            elif maybe_obj is not None and validation_error is None:
                validation_error = "assistant proposed_spec_json must decode to a JSON object"
        else:
            validation_error = "assistant did not return proposed_spec_json"

        if isinstance(proposed_raw, dict):
            sanitized_patch = _sanitize_proposal_patch(proposed_raw)
            candidate = _deep_merge(working, sanitized_patch)
            try:
                spec_obj = RunSpec.model_validate(candidate)
                validate_policy(spec_obj)
                normalized_proposed = spec_obj.model_dump()
                cmnd_preview = compile_runspec_to_text(spec_obj)
                diff_lines = spec_diff_lines(working, normalized_proposed)
                if diff_lines == ["No differences."]:
                    session["proposed_spec"] = None
                    normalized_proposed = None
                else:
                    session["proposed_spec"] = normalized_proposed
            except Exception as exc:  # pylint: disable=broad-except
                validation_error = str(exc)

        session.setdefault("messages", []).append(
            {"role": "user", "content": user_message, "at": _now_iso()}
        )
        session["messages"].append(
            {
                "role": "assistant",
                "content": parsed.get("assistant_message", ""),
                "at": _now_iso(),
                "proposal_summary": parsed.get("proposal_summary", ""),
                "run_recommended": bool(parsed.get("run_recommended", False)),
            }
        )

        self.session_store.save(session)

        return {
            "assistant_message": parsed.get("assistant_message", ""),
            "proposal_summary": parsed.get("proposal_summary", ""),
            "run_recommended": bool(parsed.get("run_recommended", False)),
            "proposed_spec": normalized_proposed,
            "proposal_diff": diff_lines,
            "cmnd_preview": cmnd_preview,
            "validation_error": validation_error,
            "model": model,
            "session": public_session_state(session),
        }


def public_session_state(session: dict[str, Any]) -> dict[str, Any]:
    working = session.get("working_spec")
    proposed = session.get("proposed_spec")

    return {
        "session_id": session.get("session_id"),
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
        "working_spec": working,
        "proposed_spec": proposed,
        "proposed_diff": spec_diff_lines(working, proposed) if isinstance(proposed, dict) else [],
        "messages": session.get("messages", []),
        "last_run_id": session.get("last_run_id"),
    }

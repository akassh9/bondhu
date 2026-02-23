from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class RunNotFoundError(FileNotFoundError):
    pass


class RunStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat()

    def _run_dir(self, run_id: str) -> Path:
        return self.root_dir / run_id

    def create_run(self, spec: dict[str, Any], cmnd_text: str, metadata: dict[str, Any] | None = None) -> str:
        run_id = uuid.uuid4().hex[:12]
        run_dir = self._run_dir(run_id)

        with self._lock:
            run_dir.mkdir(parents=True, exist_ok=False)
            created_at = self._now_iso()

            self._write_json(
                run_dir / "status.json",
                {
                    "run_id": run_id,
                    "state": "CREATED",
                    "created_at": created_at,
                    "updated_at": created_at,
                    "message": "Run created",
                    "error": None,
                },
            )
            self._write_json(run_dir / "run_spec.json", spec)
            (run_dir / "run.cmnd").write_text(cmnd_text, encoding="utf-8")
            self._write_json(run_dir / "metadata.json", metadata or {})

        return run_id

    def run_dir(self, run_id: str) -> Path:
        run_dir = self._run_dir(run_id)
        if not run_dir.exists():
            raise RunNotFoundError(run_id)
        return run_dir

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def get_status(self, run_id: str) -> dict[str, Any]:
        run_dir = self.run_dir(run_id)
        return self._read_json(run_dir / "status.json")

    def update_status(
        self,
        run_id: str,
        *,
        state: str,
        message: str | None = None,
        error: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_dir = self.run_dir(run_id)
        with self._lock:
            status_path = run_dir / "status.json"
            current = self._read_json(status_path)
            current["state"] = state
            current["updated_at"] = self._now_iso()
            if message is not None:
                current["message"] = message
            if error is not None:
                current["error"] = error
            if extra:
                current.update(extra)
            self._write_json(status_path, current)
            return current

    def write_text_artifact(self, run_id: str, filename: str, content: str) -> None:
        run_dir = self.run_dir(run_id)
        target = run_dir / filename
        target.write_text(content, encoding="utf-8")

    def write_json_artifact(self, run_id: str, filename: str, payload: dict[str, Any]) -> None:
        run_dir = self.run_dir(run_id)
        self._write_json(run_dir / filename, payload)

    def get_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        run_dir = self.run_dir(run_id)
        out: list[dict[str, Any]] = []

        for path in sorted(run_dir.iterdir()):
            if path.is_file():
                out.append({"name": path.name, "size_bytes": path.stat().st_size})

        return out

    def get_artifact_path(self, run_id: str, artifact_name: str) -> Path:
        run_dir = self.run_dir(run_id)
        target = (run_dir / artifact_name).resolve()
        if target.parent != run_dir.resolve() or not target.exists() or not target.is_file():
            raise FileNotFoundError(artifact_name)
        return target

    def get_spec(self, run_id: str) -> dict[str, Any]:
        run_dir = self.run_dir(run_id)
        return self._read_json(run_dir / "run_spec.json")

    def list_runs(self, limit: int = 20, states: set[str] | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        run_dirs = [path for path in self.root_dir.iterdir() if path.is_dir()]
        run_dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)

        for run_dir in run_dirs:
            status = self._read_json(run_dir / "status.json")
            if not status:
                continue

            state = status.get("state")
            if states and state not in states:
                continue

            out.append(status)
            if len(out) >= limit:
                break

        return out

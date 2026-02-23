from __future__ import annotations

import json
import queue
import shlex
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .analysis import generate_basic_analysis
from .diagnostics import build_teammate_summary, maybe_generate_llm_summary, parse_message_statistics
from .store import RunStore


class RunService:
    def __init__(self, store: RunStore, repo_root: Path, backend_root: Path) -> None:
        self.store = store
        self.repo_root = repo_root
        self.backend_root = backend_root

        self._queue: queue.Queue[str | None] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._compile_lock = threading.Lock()

        self._runner_src = self.backend_root / "runner" / "pythia_runner.cc"
        self._runner_bin = self.backend_root / "bin" / "pythia_runner"
        self._pythia_config = self.repo_root / "bin" / "pythia8-config"

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat()

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._queue.put(None)
        self._thread.join(timeout=3)

    def enqueue(self, run_id: str) -> dict[str, Any]:
        status = self.store.get_status(run_id)
        state = status.get("state")
        if state not in {"CREATED", "FAILED"}:
            raise ValueError(f"run {run_id} cannot be enqueued from state {state}")

        updated = self.store.update_status(run_id, state="QUEUED", message="Queued for execution", error=None)
        self._queue.put(run_id)
        return updated

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is None:
                self._queue.task_done()
                break

            try:
                self._execute_run(item)
            finally:
                self._queue.task_done()

    def _execute_run(self, run_id: str) -> None:
        run_dir = self.store.run_dir(run_id)
        cmnd_path = run_dir / "run.cmnd"
        summary_path = run_dir / "event_summary.json"

        self.store.update_status(run_id, state="RUNNING", message="Running PYTHIA job", error=None)

        try:
            self._ensure_runner_binary()
        except Exception as exc:  # pylint: disable=broad-except
            self.store.update_status(
                run_id,
                state="FAILED",
                message="Failed to build runner binary",
                error=str(exc),
            )
            return

        spec = self.store.get_spec(run_id)
        timeout_s = self._estimate_timeout_seconds(spec)

        cmd = [str(self._runner_bin), str(cmnd_path), str(summary_path)]
        self.store.write_json_artifact(
            run_id,
            "execution.json",
            {
                "command": cmd,
                "cwd": str(self.repo_root),
                "started_at": self._now_iso(),
                "timeout_seconds": timeout_s,
            },
        )

        try:
            completed = subprocess.run(
                cmd,
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            self.store.write_text_artifact(run_id, "stdout.log", exc.stdout or "")
            self.store.write_text_artifact(run_id, "stderr.log", exc.stderr or "")
            self.store.update_status(
                run_id,
                state="FAILED",
                message="Job timed out",
                error=f"Exceeded timeout of {timeout_s} seconds",
            )
            return
        except Exception as exc:  # pylint: disable=broad-except
            self.store.update_status(run_id, state="FAILED", message="Job failed", error=str(exc))
            return

        self.store.write_text_artifact(run_id, "stdout.log", completed.stdout)
        self.store.write_text_artifact(run_id, "stderr.log", completed.stderr)

        status = "SUCCEEDED" if completed.returncode == 0 else "FAILED"
        message = "Run completed" if completed.returncode == 0 else "Runner exited with non-zero status"

        extra: dict[str, Any] = {
            "exit_code": completed.returncode,
            "finished_at": self._now_iso(),
        }

        if summary_path.exists():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                summary = None
            if summary is not None:
                extra["event_summary"] = summary

        diagnostics = parse_message_statistics(completed.stdout)
        extra["diagnostics"] = diagnostics
        self.store.write_json_artifact(run_id, "diagnostics.json", diagnostics)

        teammate_summary = build_teammate_summary(
            spec=spec,
            event_summary=extra.get("event_summary"),
            diagnostics=diagnostics,
            exit_code=completed.returncode,
        )
        extra["teammate_summary"] = teammate_summary
        self.store.write_json_artifact(run_id, "teammate_summary.json", teammate_summary)

        llm_summary = maybe_generate_llm_summary(spec, teammate_summary, diagnostics)
        if llm_summary is not None:
            extra["llm_run_summary"] = llm_summary
            self.store.write_json_artifact(run_id, "llm_run_summary.json", llm_summary)

        if status == "SUCCEEDED":
            try:
                analysis = generate_basic_analysis(
                    run_dir=run_dir,
                    spec=spec,
                    event_summary=extra.get("event_summary"),
                )
                extra["analysis"] = analysis
            except Exception as exc:  # pylint: disable=broad-except
                extra["analysis_error"] = str(exc)

        self.store.update_status(
            run_id,
            state=status,
            message=message,
            error=None if completed.returncode == 0 else f"exit code {completed.returncode}",
            extra=extra,
        )

    def _estimate_timeout_seconds(self, spec: dict[str, Any]) -> int:
        events = int(spec.get("events", 10_000))
        base = max(60, min(1800, int(events / 2000) * 60))

        merging = bool(spec.get("merging", {}).get("enabled", False))
        jet = bool(spec.get("jet_matching", {}).get("enabled", False))
        if merging:
            base = int(base * 1.7)
        if jet:
            base = int(base * 1.4)

        return min(base, 3600)

    def _ensure_runner_binary(self) -> None:
        with self._compile_lock:
            if not self._pythia_config.exists():
                raise FileNotFoundError(f"pythia8-config missing: {self._pythia_config}")

            if self._runner_bin.exists() and self._runner_bin.stat().st_mtime >= self._runner_src.stat().st_mtime:
                return

            self._runner_bin.parent.mkdir(parents=True, exist_ok=True)

            cxxflags = self._read_config_flags("--cxxflags")
            libs = self._read_config_flags("--libs")

            cmd = [
                "c++",
                "-O2",
                "-std=c++17",
                str(self._runner_src),
                *shlex.split(cxxflags),
                *shlex.split(libs),
                "-o",
                str(self._runner_bin),
            ]

            completed = subprocess.run(
                cmd,
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                check=False,
            )

            if completed.returncode != 0:
                raise RuntimeError(
                    "failed to build runner binary: "
                    f"stdout={completed.stdout.strip()} stderr={completed.stderr.strip()}"
                )

    def _read_config_flags(self, arg: str) -> str:
        completed = subprocess.run(
            [str(self._pythia_config), arg],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"pythia8-config {arg} failed: {completed.stderr.strip()}")
        return completed.stdout.strip()

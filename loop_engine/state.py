from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, MutableMapping, Optional

from .errors import LoopError
from .models import Plan, TASK_PENDING


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run_id(task_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return "%s-%s" % (stamp, task_id)


class StateStore:
    """Durable local state with one process-level mutation authority."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock_path = path.with_suffix(path.suffix + ".lock")

    @contextmanager
    def lock(self, blocking: bool = False) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            flags = fcntl.LOCK_EX
            if not blocking:
                flags |= fcntl.LOCK_NB
            try:
                fcntl.flock(handle.fileno(), flags)
            except BlockingIOError:
                raise LoopError(
                    "E_LOCK_HELD",
                    "Another loop-engine process owns %s" % self.lock_path,
                    exit_code=20,
                )
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {
                "version": 1,
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "active_run": None,
                "tasks": {},
                "runs": [],
            }
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LoopError(
                "E_STATE_CORRUPT",
                "Cannot load loop state %s: %s" % (self.path, exc),
                exit_code=70,
            )
        if not isinstance(value, dict) or value.get("version") != 1:
            raise LoopError("E_STATE_CORRUPT", "Unsupported loop state format", exit_code=70)
        return value

    def save(self, state: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        value = dict(state)
        value["updated_at"] = utc_now()
        fd, temp_name = tempfile.mkstemp(
            prefix=self.path.name + ".", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def reconcile_plan(self, state: MutableMapping[str, Any], plan: Plan) -> None:
        task_states = state.setdefault("tasks", {})
        for task in plan.tasks:
            task_states.setdefault(
                task.id,
                {
                    "status": TASK_PENDING,
                    "attempts": 0,
                    "repair_cycles": 0,
                    "updated_at": utc_now(),
                },
            )


class EventLog:
    def __init__(self, run_root: Path) -> None:
        self.run_root = run_root
        self.global_path = run_root.parent / "events.jsonl"

    def emit(
        self,
        event: str,
        *,
        run_id: Optional[str] = None,
        task_id: Optional[str] = None,
        phase: Optional[str] = None,
        outcome: Optional[str] = None,
        message: Optional[str] = None,
        details: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "timestamp": utc_now(),
            "event": event,
        }
        if run_id is not None:
            payload["run_id"] = run_id
        if task_id is not None:
            payload["task_id"] = task_id
        if phase is not None:
            payload["phase"] = phase
        if outcome is not None:
            payload["outcome"] = outcome
        if message is not None:
            payload["message"] = message
        if details:
            payload["details"] = dict(details)

        self._append(self.global_path, payload)
        if run_id:
            self._append(self.run_root / run_id / "events.jsonl", payload)
        return payload

    @staticmethod
    def _append(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())


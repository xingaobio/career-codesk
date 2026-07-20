from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from .engine import RunEngine
from .errors import LoopError


def _repository_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in (current,) + tuple(current.parents):
        if (candidate / ".git").exists():
            return candidate
    raise LoopError("E_NOT_GIT_REPOSITORY", "No Git repository found above %s" % start)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="career-loop",
        description="Run isolated Sol-guided, Terra/Luna-implemented Career CoDesk tasks.",
    )
    parser.add_argument("--repo", type=Path, help="Repository root (defaults to discovery from cwd)")
    parser.add_argument("--workflow", type=Path, help="WORKFLOW.md path (defaults to repository root)")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor", help="Validate workflow, plan, Git inputs, and model profiles")
    doctor.add_argument("--no-model-check", action="store_true")

    commands.add_parser("status", help="Show the durable task projection")

    once = commands.add_parser("once", help="Run one dependency-ready task")
    once.add_argument("task_id", nargs="?")
    once.add_argument("--dry-run", action="store_true")

    run = commands.add_parser("run", help="Run accepted tasks until complete or attention is required")
    run.add_argument("--max-tasks", type=int)

    approve = commands.add_parser("approve", help="Approve a ready human gate on the integration branch")
    approve.add_argument("task_id")
    approve.add_argument("--approver", required=True, help="Approver role or name recorded in evidence")
    approve.add_argument("--note", required=True)

    reject = commands.add_parser("reject", help="Reject a ready human gate and stop the plan")
    reject.add_argument("task_id")
    reject.add_argument("--approver", required=True, help="Rejector role or name recorded in evidence")
    reject.add_argument("--note", required=True)

    retry = commands.add_parser("retry", help="Requeue a blocked or failed task, preserving its worktree")
    retry.add_argument("task_id")
    retry.add_argument("--note", default="", help="Resolution for a blocked human question")

    pause = commands.add_parser("pause", help="Mark an interrupted active task as paused and resumable")
    pause.add_argument("task_id")
    pause.add_argument("--note", default="", help="Optional operator note recorded in local evidence")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        repo = (args.repo or _repository_root(Path.cwd())).resolve()
        if args.workflow:
            workflow = args.workflow
            if not workflow.is_absolute():
                workflow = repo / workflow
            workflow = workflow.resolve()
        else:
            workflow = repo / "WORKFLOW.md"
        engine = RunEngine(repo, workflow)

        if args.command == "doctor":
            report = engine.doctor(check_models=not args.no_model_check)
            _render(report.to_dict(), args.json)
            return 0 if report.execution_ready else 10
        if args.command == "status":
            _render(engine.status(), args.json)
            return 0
        if args.command == "once":
            outcome = engine.run_once(args.task_id, dry_run=args.dry_run)
            _render(outcome.to_dict(), args.json)
            return _outcome_exit(outcome.status)
        if args.command == "run":
            if args.max_tasks is not None and args.max_tasks <= 0:
                raise LoopError("E_ARGUMENT", "--max-tasks must be positive")
            outcomes = engine.run_loop(args.max_tasks)
            payload = {
                "status": outcomes[-1].status if outcomes else "complete",
                "outcomes": [outcome.to_dict() for outcome in outcomes],
            }
            _render(payload, args.json)
            return _outcome_exit(payload["status"])
        if args.command == "approve":
            outcome = engine.approve(args.task_id, args.note, args.approver)
            _render(outcome.to_dict(), args.json)
            return _outcome_exit(outcome.status)
        if args.command == "reject":
            outcome = engine.reject(args.task_id, args.note, args.approver)
            _render(outcome.to_dict(), args.json)
            return _outcome_exit(outcome.status)
        if args.command == "retry":
            outcome = engine.retry(args.task_id, args.note)
            _render(outcome.to_dict(), args.json)
            return 0
        if args.command == "pause":
            outcome = engine.pause(args.task_id, args.note)
            _render(outcome.to_dict(), args.json)
            return 0
        parser.error("unknown command")
    except KeyboardInterrupt:
        _render_error("E_INTERRUPTED", "Interrupted by operator", args.json)
        return 130
    except LoopError as exc:
        _render(exc.to_dict(), args.json, error=True)
        return exc.exit_code
    return 70


def _outcome_exit(status: str) -> int:
    if status in {"needs_human", "blocked"}:
        return 10
    if status in {"failed"}:
        return 50
    return 0


def _render(value: Mapping[str, Any], as_json: bool, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    if as_json:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
        return
    _render_human(value, stream, indent=0)


def _render_human(value: Any, stream: Any, indent: int) -> None:
    prefix = " " * indent
    if isinstance(value, Mapping):
        for key, child in value.items():
            if child in (None, [], {}, ()):
                continue
            if isinstance(child, (Mapping, list, tuple)):
                stream.write("%s%s:\n" % (prefix, key))
                _render_human(child, stream, indent + 2)
            else:
                stream.write("%s%s: %s\n" % (prefix, key, child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            if isinstance(child, (Mapping, list, tuple)):
                stream.write("%s-\n" % prefix)
                _render_human(child, stream, indent + 2)
            else:
                stream.write("%s- %s\n" % (prefix, child))
    else:
        stream.write("%s%s\n" % (prefix, value))


def _render_error(code: str, message: str, as_json: bool) -> None:
    _render({"code": code, "message": message}, as_json, error=True)


if __name__ == "__main__":
    raise SystemExit(main())

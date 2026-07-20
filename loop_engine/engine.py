from __future__ import annotations

import fnmatch
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from .agent import AgentPort, CodexCliAdapter, Verifier, verification_summary
from .config import load_plan, load_workflow
from .errors import AgentError, GitSafetyError, LoopError, RunFailed
from .git_ops import GitRepository
from .models import (
    AgentRequest,
    DoctorReport,
    Plan,
    RunOutcome,
    TASK_ACCEPTED,
    TASK_BLOCKED,
    TASK_FAILED,
    TASK_PENDING,
    TASK_RUNNING,
    TASK_WAITING_HUMAN,
    Task,
    VerificationResult,
    Workflow,
    task_to_prompt_dict,
)
from .prompts import guide_prompt, implement_prompt, repair_prompt, review_prompt
from .schemas import GUIDE_SCHEMA, REVIEW_SCHEMA
from .state import EventLog, StateStore, new_run_id, utc_now


_CHECKPOINT_VERSION = 1
_MAX_VERIFICATION_STABILITY_PASSES = 3


class RunEngine:
    """One fixed guide -> implement -> verify -> review -> repair loop."""

    def __init__(
        self,
        repo_root: Path,
        workflow_path: Optional[Path] = None,
        agent: Optional[AgentPort] = None,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.workflow_path = (workflow_path or (self.repo_root / "WORKFLOW.md")).resolve()
        self._injected_agent = agent

    def doctor(self, check_models: bool = True) -> DoctorReport:
        workflow, plan, git, _, _ = self._context()
        problems: List[Mapping[str, Any]] = []
        warnings: List[str] = []
        models: Dict[str, Mapping[str, str]] = {}

        try:
            git.validate_repository()
        except LoopError as exc:
            problems.append(exc.to_dict())

        base_ref = workflow.integration_branch if git.branch_exists(workflow.integration_branch) else "HEAD"
        state = StateStore(workflow.state_path).load()
        StateStore(workflow.state_path).reconcile_plan(state, plan)
        self._reconcile_accepted(state, plan, git, workflow)
        for task in plan.tasks:
            runtime = state["tasks"][task.id]
            if runtime.get("stage") == "acceptance_stale":
                error = runtime.get("error")
                if isinstance(error, Mapping):
                    problems.append(dict(error))
        required_paths = self._policy_paths(workflow)
        ready = [
            task
            for task in sorted(plan.tasks, key=lambda item: (item.priority, item.id))
            if state["tasks"][task.id].get("status") in {TASK_PENDING, TASK_WAITING_HUMAN}
            and all(
                state["tasks"][dependency].get("status") == TASK_ACCEPTED
                for dependency in task.depends_on
            )
        ]
        if ready:
            required_paths = list(dict.fromkeys(required_paths + list(ready[0].source_paths)))
        for path in required_paths:
            if not git.path_exists_at(base_ref, path):
                problems.append(
                    {
                        "code": "E_SOURCE_NOT_IN_BASE",
                        "message": "%s is not present in pinned base %s" % (path, base_ref),
                        "details": {"path": path, "base_ref": base_ref},
                    }
                )
        dirty = git.dirty_paths(required_paths)
        if dirty:
            problems.append(
                {
                    "code": "E_DIRTY_POLICY_INPUT",
                    "message": "Policy inputs have uncommitted changes",
                    "details": {"paths": dirty},
                }
            )

        used_profiles = {"guide", "reviewer"}
        used_profiles.update(task.agent_profile for task in plan.tasks if task.mode == "agent")
        if check_models:
            try:
                catalog = self._agent(workflow).capabilities()
                self._validate_catalog_shape(catalog)
                for name, profile in workflow.model_profiles.items():
                    capability = catalog.get(profile.model)
                    available = isinstance(capability, Mapping)
                    efforts = capability.get("reasoning_efforts", []) if available else []
                    supported = isinstance(efforts, Sequence) and not isinstance(efforts, str)
                    effort_available = supported and profile.reasoning_effort in efforts
                    models[name] = {
                        "model": profile.model,
                        "reasoning_effort": profile.reasoning_effort,
                        "sandbox": profile.sandbox,
                        "available": "yes" if available and effort_available else "no",
                    }
                    issue: Optional[Mapping[str, Any]] = None
                    if not available:
                        issue = {
                            "code": "E_MODEL_UNAVAILABLE",
                            "message": "%s is unavailable for profile %s" % (profile.model, name),
                            "details": {},
                        }
                    elif not effort_available:
                        issue = {
                            "code": "E_REASONING_UNAVAILABLE",
                            "message": "%s does not support %s reasoning for profile %s"
                            % (profile.model, profile.reasoning_effort, name),
                            "details": {},
                        }
                    if issue and name in used_profiles:
                        problems.append(issue)
                    elif issue:
                        warnings.append(issue["message"] + " (unused optional profile)")
            except LoopError as exc:
                problems.append(exc.to_dict())
        else:
            for name, profile in workflow.model_profiles.items():
                models[name] = {
                    "model": profile.model,
                    "reasoning_effort": profile.reasoning_effort,
                    "sandbox": profile.sandbox,
                    "available": "unchecked",
                }

        return DoctorReport(
            structurally_valid=True,
            execution_ready=not problems,
            repo_root=str(self.repo_root),
            workflow_path=str(workflow.path),
            plan_path=str(workflow.plan_path),
            models=models,
            problems=tuple(problems),
            warnings=tuple(warnings),
        )

    def status(self) -> Mapping[str, Any]:
        workflow, plan, git, store, _ = self._context()
        state = store.load()
        store.reconcile_plan(state, plan)
        self._reconcile_accepted(state, plan, git, workflow)
        rows = []
        for task in sorted(plan.tasks, key=lambda item: (item.priority, item.id)):
            runtime = state["tasks"][task.id]
            rows.append(
                {
                    "id": task.id,
                    "title": task.title,
                    "mode": task.mode,
                    "status": runtime.get("status", TASK_PENDING),
                    "stage": runtime.get("stage", "pending"),
                    "attempts": runtime.get("attempts", 0),
                    "repair_cycles": runtime.get("repair_cycles", 0),
                    "questions": runtime.get("questions", []),
                    "gate_request": runtime.get("gate_request")
                    if runtime.get("status") == TASK_WAITING_HUMAN
                    else None,
                    "gate_decision": runtime.get("gate_decision"),
                }
            )
        return {
            "project": plan.project,
            "active_run": state.get("active_run"),
            "integration_branch": workflow.integration_branch,
            "tasks": rows,
        }

    def run_once(self, task_id: Optional[str] = None, dry_run: bool = False) -> RunOutcome:
        workflow, plan, git, store, events = self._context()
        if dry_run:
            state = store.load()
            store.reconcile_plan(state, plan)
            self._reconcile_accepted(state, plan, git, workflow)
            task = self._select_task(plan, state, task_id)
            if task is None:
                return self._idle_outcome(plan, state)
            base_ref = workflow.integration_branch if git.branch_exists(workflow.integration_branch) else "HEAD"
            base_commit = self._preflight_task(workflow, task, git, base_ref)
            details: Dict[str, Any] = {
                "base_ref": base_ref,
                "base_commit": base_commit,
                "mode": task.mode,
            }
            if task.mode == "agent":
                model_snapshot = self._preflight_models(workflow, task, git)
                details["models"] = model_snapshot
            return RunOutcome(
                status="dry_run",
                summary=(
                    "Task %s is ready; no lock, state, branches, worktrees, or agents were changed."
                    % task.id
                ),
                task_id=task.id,
                branch=(
                    workflow.integration_branch
                    if task.mode == "human"
                    else "%s%s" % (workflow.task_branch_prefix, task.id)
                ),
                details=details,
            )

        with store.lock():
            self._reconcile_child_processes(workflow)
            state = store.load()
            store.reconcile_plan(state, plan)
            if self._reconcile_accepted(state, plan, git, workflow):
                store.save(state)
            task = self._select_task(plan, state, task_id)
            if task is None:
                return self._idle_outcome(plan, state)

            base_ref = workflow.integration_branch if git.branch_exists(workflow.integration_branch) else "HEAD"
            base_commit = self._preflight_task(workflow, task, git, base_ref)
            model_snapshot: Mapping[str, Any] = {}
            if task.mode == "agent":
                model_snapshot = self._preflight_models(workflow, task, git)

            integration_worktree = git.ensure_integration_worktree(
                workflow.integration_branch, workflow.workspace_root, base_ref
            )
            if task.mode == "human":
                return self._wait_for_human_gate(
                    workflow, task, git, store, events, state, integration_worktree
                )

            branch, worktree = git.ensure_task_worktree(
                task.id,
                workflow.task_branch_prefix,
                workflow.integration_branch,
                workflow.workspace_root,
            )
            start_commit = git.resolve_ref_at(integration_worktree, "HEAD")
            branch_head = git.resolve_ref_at(worktree, "HEAD")
            runtime = state["tasks"][task.id]
            if branch_head != start_commit:
                checkpoint = self._recoverable_checkpoint(
                    runtime, task, workflow, git, branch_head, expected_kind="agent"
                )
                if checkpoint is None or checkpoint["base_commit"] != start_commit:
                    raise GitSafetyError(
                        "E_AGENT_GIT_MUTATION",
                        "Task branch %s moved without a matching durable engine checkpoint" % branch,
                    )
                runtime["checkpoint"] = checkpoint
                runtime.pop("checkpoint_intent", None)
                runtime["stage"] = "checkpointed"
                store.save(state)
                integrated = git.integrate_fast_forward(integration_worktree, branch)
                self._accept_task(
                    state,
                    task,
                    integrated,
                    branch,
                    worktree,
                    repair_cycles=int(runtime.get("repair_cycles", 0)),
                )
                store.save(state)
                events.emit(
                    "run_recovered",
                    run_id=runtime.get("run_id"),
                    task_id=task.id,
                    phase="finishing",
                    outcome="accepted",
                    details={"commit": integrated, "tree_digest": checkpoint["reviewed_tree"]},
                )
                return RunOutcome(
                    status="accepted",
                    summary="Recovered and integrated previously reviewed task %s." % task.id,
                    task_id=task.id,
                    branch=branch,
                    worktree=str(worktree),
                    repair_cycles=int(runtime.get("repair_cycles", 0)),
                    details={"commit": integrated, "tree_digest": checkpoint["reviewed_tree"]},
                )

            active = state.get("active_run") or {}
            resuming = (
                active.get("task_id") == task.id and runtime.get("status") == TASK_RUNNING
            )
            if resuming:
                run_id = self._validated_run_id(active.get("run_id"))
                if active.get("branch") != branch or Path(str(active.get("worktree", ""))).resolve() != worktree:
                    raise GitSafetyError(
                        "E_ACTIVE_RUN_STATE", "Active run no longer matches its isolated worktree"
                    )
                if runtime.get("base_commit") != start_commit:
                    raise GitSafetyError(
                        "E_ACTIVE_RUN_STALE", "Integration base changed while the run was interrupted"
                    )
                resume_stage = str(runtime.get("stage", "guiding"))
                repairs = int(runtime.get("repair_cycles", 0))
            else:
                if int(runtime.get("attempts", 0)) == 0 and git.has_changes(worktree):
                    raise GitSafetyError(
                        "E_WORKTREE_DIRTY_UNKNOWN",
                        "New task worktree contains changes without a prior attempt",
                    )
                run_id = new_run_id(task.id)
                resume_stage = "guiding"
                repairs = 0
                runtime.pop("checkpoint", None)
                runtime.pop("checkpoint_intent", None)
                runtime.update(
                    {
                        "status": TASK_RUNNING,
                        "attempts": int(runtime.get("attempts", 0)) + 1,
                        "repair_cycles": 0,
                        "updated_at": utc_now(),
                        "run_id": run_id,
                        "branch": branch,
                        "worktree": str(worktree),
                        "base_commit": start_commit,
                        "task_digest": self._task_digest(task),
                        "workflow_digest": self._workflow_digest(workflow),
                        "stage": "guiding",
                        "questions": [],
                    }
                )
                state["active_run"] = {
                    "run_id": run_id,
                    "task_id": task.id,
                    "branch": branch,
                    "worktree": str(worktree),
                    "stage": "guiding",
                    "started_at": utc_now(),
                }
                store.save(state)
                events.emit(
                    "run_started",
                    run_id=run_id,
                    task_id=task.id,
                    phase="guiding",
                    outcome="started",
                    details={"branch": branch, "worktree": str(worktree), "base_commit": start_commit},
                )

            run_dir = workflow.run_root / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "models.json").write_text(
                json.dumps(model_snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            agent = self._agent(workflow)
            reconcile_agent = getattr(agent, "reconcile", None)
            if callable(reconcile_agent):
                reconcile_agent(run_dir)
            verifier = Verifier(workflow.strip_environment)
            verifier.reconcile(run_dir)

            try:
                if resuming and resume_stage in {"implementing", "repairing"}:
                    raise RunFailed(
                        "E_AMBIGUOUS_MUTATION",
                        "Run stopped during %s; inspect the preserved worktree and retry explicitly"
                        % resume_stage,
                    )
                return self._execute_task(
                    workflow=workflow,
                    task=task,
                    git=git,
                    store=store,
                    events=events,
                    state=state,
                    run_id=run_id,
                    run_dir=run_dir,
                    integration_worktree=integration_worktree,
                    branch=branch,
                    worktree=worktree,
                    start_commit=start_commit,
                    agent=agent,
                    verifier=verifier,
                    repairs=repairs,
                    skip_implementation=resuming
                    and resume_stage in {"verifying", "reviewing", "checkpointing"},
                )
            except LoopError as exc:
                checkpointed = isinstance(runtime.get("checkpoint"), Mapping)
                runtime.update(
                    {
                        "status": TASK_FAILED,
                        "stage": "checkpointed" if checkpointed else "failed",
                        "error": exc.to_dict(),
                        "updated_at": utc_now(),
                    }
                )
                state["active_run"] = None
                store.save(state)
                events.emit(
                    "run_failed",
                    run_id=run_id,
                    task_id=task.id,
                    phase="failed",
                    outcome="failed",
                    message=exc.message,
                    details={"code": exc.code, "checkpointed": checkpointed},
                )
                raise
            except Exception as exc:
                wrapped = LoopError(
                    "E_INTERNAL",
                    "Unexpected %s while running task %s" % (type(exc).__name__, task.id),
                    exit_code=70,
                )
                checkpointed = isinstance(runtime.get("checkpoint"), Mapping)
                runtime.update(
                    {
                        "status": TASK_FAILED,
                        "stage": "checkpointed" if checkpointed else "failed",
                        "error": wrapped.to_dict(),
                        "updated_at": utc_now(),
                    }
                )
                state["active_run"] = None
                store.save(state)
                events.emit(
                    "run_failed",
                    run_id=run_id,
                    task_id=task.id,
                    phase="failed",
                    outcome="failed",
                    message=wrapped.message,
                    details={"code": wrapped.code, "checkpointed": checkpointed},
                )
                raise wrapped from exc

    def run_loop(self, max_tasks: Optional[int] = None) -> Sequence[RunOutcome]:
        outcomes = []
        while max_tasks is None or len(
            [item for item in outcomes if item.status == "accepted"]
        ) < max_tasks:
            outcome = self.run_once()
            outcomes.append(outcome)
            if outcome.status != "accepted":
                break
        return outcomes

    def approve(self, task_id: str, note: str, approver: str) -> RunOutcome:
        note, approver = self._validate_gate_attestation(note, approver, "approval")
        workflow, plan, git, store, events = self._context()
        task = plan.by_id().get(task_id)
        if not task:
            raise LoopError("E_TASK_NOT_FOUND", "Unknown task: %s" % task_id)
        if task.mode != "human":
            raise LoopError("E_NOT_HUMAN_GATE", "%s is not a human gate" % task_id)
        with store.lock():
            self._reconcile_child_processes(workflow)
            state = store.load()
            store.reconcile_plan(state, plan)
            if self._reconcile_accepted(state, plan, git, workflow):
                store.save(state)
            runtime = state["tasks"][task.id]
            if runtime.get("status") == TASK_ACCEPTED:
                raise LoopError("E_TASK_ALREADY_ACCEPTED", "%s is already accepted" % task.id)
            if runtime.get("status") != TASK_WAITING_HUMAN:
                raise LoopError(
                    "E_GATE_NOT_WAITING", "Run the human gate once before approving it"
                )
            missing = [
                dependency
                for dependency in task.depends_on
                if state["tasks"][dependency].get("status") != TASK_ACCEPTED
            ]
            if missing:
                raise LoopError(
                    "E_GATE_DEPENDENCIES",
                    "Human gate %s is waiting on: %s" % (task.id, ", ".join(missing)),
                )
            request = runtime.get("gate_request")
            if not isinstance(request, Mapping):
                raise GitSafetyError("E_GATE_STALE", "Human gate request metadata is missing")
            if (
                request.get("task_digest") != self._task_digest(task)
                or request.get("workflow_digest") != self._workflow_digest(workflow)
            ):
                raise GitSafetyError("E_GATE_STALE", "Human gate policy changed after review began")
            base_ref = workflow.integration_branch if git.branch_exists(workflow.integration_branch) else "HEAD"
            self._preflight_task(workflow, task, git, base_ref)
            integration_worktree = git.ensure_integration_worktree(
                workflow.integration_branch, workflow.workspace_root, base_ref
            )
            gate_base = git.resolve_ref_at(integration_worktree, "HEAD")
            if request.get("expected_base") != gate_base:
                raise GitSafetyError("E_GATE_STALE", "Integration branch changed after gate issuance")

            gate_run_id = new_run_id(task.id + "-gate")
            gate_evidence = workflow.run_root / gate_run_id / "gate-verification"
            verifier = Verifier(workflow.strip_environment)
            verifier.reconcile(gate_evidence.parent)
            results, summary, reviewed_tree = self._verify_stable(
                workflow,
                task,
                git,
                verifier,
                integration_worktree,
                gate_base,
                gate_evidence,
            )
            if not all(result.passed for result in results):
                raise RunFailed("E_GATE_VERIFY", "Human gate verification failed:\n%s" % summary)

            intent = self._checkpoint_intent(task, workflow, gate_base, reviewed_tree, "human")
            intent.update(
                {
                    "request_id": request.get("request_id"),
                    "approver": approver,
                    "note": note,
                }
            )
            runtime["approval_intent"] = intent
            runtime["stage"] = "checkpointing"
            store.save(state)
            commit = git.commit_human_gate(
                integration_worktree,
                workflow.integration_branch,
                gate_base,
                reviewed_tree,
                task.id,
                task.title,
                note,
                approver,
            )
            checkpoint = self._checkpoint_from_intent(intent, commit)
            runtime["checkpoint"] = checkpoint
            runtime.pop("approval_intent", None)
            runtime["approval"] = {
                "request_id": request.get("request_id"),
                "approver": approver,
                "note": note,
                "base_commit": gate_base,
                "tree_digest": reviewed_tree,
                "commit": commit,
                "approved_at": utc_now(),
            }
            runtime.setdefault("gate_decisions", []).append(
                {
                    "request_id": request.get("request_id"),
                    "decision": "approved",
                    "approver": approver,
                    "note": note,
                    "base_commit": gate_base,
                    "tree_digest": reviewed_tree,
                    "commit": commit,
                    "decided_at": utc_now(),
                }
            )
            self._accept_task(
                state, task, commit, workflow.integration_branch, integration_worktree, 0
            )
            store.save(state)
            events.emit(
                "human_gate_approved",
                run_id=gate_run_id,
                task_id=task.id,
                phase="gate",
                outcome="accepted",
                message=note,
                details={
                    "approver": approver,
                    "request_id": request.get("request_id"),
                    "commit": commit,
                    "tree_digest": reviewed_tree,
                    "evidence": str(gate_evidence),
                },
            )
            return RunOutcome(
                status="accepted",
                summary="Approved human gate %s on %s." % (task.id, commit[:12]),
                task_id=task.id,
                run_id=gate_run_id,
                branch=workflow.integration_branch,
                worktree=str(integration_worktree),
                details={
                    "commit": commit,
                    "tree_digest": reviewed_tree,
                    "request_id": request.get("request_id"),
                    "approver": approver,
                    "evidence": str(gate_evidence),
                },
            )

    def reject(self, task_id: str, note: str, approver: str) -> RunOutcome:
        note, approver = self._validate_gate_attestation(note, approver, "rejection")
        workflow, plan, git, store, events = self._context()
        task = plan.by_id().get(task_id)
        if not task:
            raise LoopError("E_TASK_NOT_FOUND", "Unknown task: %s" % task_id)
        if task.mode != "human":
            raise LoopError("E_NOT_HUMAN_GATE", "%s is not a human gate" % task_id)
        with store.lock():
            self._reconcile_child_processes(workflow)
            state = store.load()
            store.reconcile_plan(state, plan)
            if self._reconcile_accepted(state, plan, git, workflow):
                store.save(state)
            runtime = state["tasks"][task.id]
            if runtime.get("status") == TASK_ACCEPTED:
                raise LoopError("E_TASK_ALREADY_ACCEPTED", "%s is already accepted" % task.id)
            if runtime.get("status") != TASK_WAITING_HUMAN:
                raise LoopError(
                    "E_GATE_NOT_WAITING", "Run the human gate once before rejecting it"
                )
            request = runtime.get("gate_request")
            if not isinstance(request, Mapping):
                raise GitSafetyError("E_GATE_STALE", "Human gate request metadata is missing")
            if (
                request.get("task_digest") != self._task_digest(task)
                or request.get("workflow_digest") != self._workflow_digest(workflow)
                or not git.branch_exists(workflow.integration_branch)
                or request.get("expected_base")
                != git.resolve_ref(workflow.integration_branch)
            ):
                raise GitSafetyError(
                    "E_GATE_STALE", "Human gate policy or integration base changed"
                )
            decision = {
                "request_id": request.get("request_id"),
                "decision": "rejected",
                "approver": approver,
                "note": note,
                "base_commit": request.get("expected_base"),
                "decided_at": utc_now(),
            }
            runtime.setdefault("gate_decisions", []).append(decision)
            runtime.update(
                {
                    "status": TASK_BLOCKED,
                    "stage": "gate_rejected",
                    "gate_decision": decision,
                    "questions": [
                        "Address the recorded gate rejection before asking for another decision."
                    ],
                    "updated_at": utc_now(),
                }
            )
            state["active_run"] = None
            store.save(state)
            events.emit(
                "human_gate_rejected",
                task_id=task.id,
                phase="gate",
                outcome="rejected",
                message=note,
                details={
                    "approver": approver,
                    "request_id": request.get("request_id"),
                    "base_commit": request.get("expected_base"),
                },
            )
            return RunOutcome(
                status="blocked",
                summary="Rejected human gate %s; the plan remains stopped." % task.id,
                task_id=task.id,
                branch=workflow.integration_branch,
                details=decision,
            )

    def retry(self, task_id: str, note: str = "") -> RunOutcome:
        workflow, plan, git, store, events = self._context()
        if task_id not in plan.by_id():
            raise LoopError("E_TASK_NOT_FOUND", "Unknown task: %s" % task_id)
        with store.lock():
            self._reconcile_child_processes(workflow)
            state = store.load()
            store.reconcile_plan(state, plan)
            if self._reconcile_accepted(state, plan, git, workflow):
                store.save(state)
            runtime = state["tasks"][task_id]
            status = runtime.get("status")
            if status == TASK_ACCEPTED:
                raise LoopError("E_TASK_ALREADY_ACCEPTED", "%s is already accepted" % task_id)
            if status == TASK_WAITING_HUMAN:
                raise LoopError(
                    "E_GATE_DECISION_REQUIRED",
                    "%s is a waiting gate; use approve or reject" % task_id,
                )
            if status not in {TASK_BLOCKED, TASK_FAILED}:
                raise LoopError(
                    "E_TASK_NOT_RETRYABLE", "%s is %s, not blocked or failed" % (task_id, status)
                )
            questions = runtime.get("questions", [])
            resolution = note.strip()
            if status == TASK_BLOCKED and questions and not resolution:
                raise LoopError(
                    "E_RESOLUTION_NOTE_REQUIRED",
                    "Answer the blocked question with retry --note",
                )
            if resolution:
                runtime.setdefault("resolution_notes", []).append(
                    {
                        "note": resolution,
                        "questions": list(questions) if isinstance(questions, list) else [],
                        "recorded_at": utc_now(),
                    }
                )
            runtime.update(
                {
                    "status": TASK_PENDING,
                    "stage": "checkpointed"
                    if isinstance(runtime.get("checkpoint"), Mapping)
                    else "pending",
                    "error": None,
                    "questions": [],
                    "updated_at": utc_now(),
                }
            )
            active_run = state.get("active_run") or {}
            if active_run.get("task_id") == task_id:
                state["active_run"] = None
            store.save(state)
            events.emit(
                "task_requeued",
                task_id=task_id,
                phase="pending",
                outcome="ready",
                details={"resolution_note_recorded": bool(resolution)},
            )
            return RunOutcome(
                status="pending",
                summary="Task %s is ready to retry; its isolated worktree was preserved." % task_id,
                task_id=task_id,
            )

    def _execute_task(
        self,
        *,
        workflow: Workflow,
        task: Task,
        git: GitRepository,
        store: StateStore,
        events: EventLog,
        state: MutableMapping[str, Any],
        run_id: str,
        run_dir: Path,
        integration_worktree: Path,
        branch: str,
        worktree: Path,
        start_commit: str,
        agent: AgentPort,
        verifier: Verifier,
        repairs: int,
        skip_implementation: bool,
    ) -> RunOutcome:
        runtime = state["tasks"][task.id]
        guide_path = run_dir / "guide.json"
        guidance: Optional[Mapping[str, Any]] = None
        if guide_path.exists():
            try:
                candidate = json.loads(guide_path.read_text(encoding="utf-8"))
                self._validate_guide(candidate, task)
                guidance = candidate
            except (json.JSONDecodeError, AgentError):
                guidance = None
        if guidance is None:
            guide_response = self._run_agent_guarded(
                git,
                agent,
                AgentRequest(
                    role="guide",
                    profile=workflow.model_profiles["guide"],
                    prompt=guide_prompt(
                        workflow,
                        task,
                        start_commit,
                        runtime.get("resolution_notes", []),
                    ),
                    cwd=worktree,
                    run_dir=run_dir,
                    response_schema=GUIDE_SCHEMA,
                ),
                workflow.turn_timeout_seconds,
            )
            self._validate_guide(guide_response.output, task)
            guidance = guide_response.output
            guide_path.write_text(
                json.dumps(guidance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        if guidance["decision"] == "needs_human":
            return self._block_for_human(
                state,
                store,
                events,
                task,
                run_id,
                "guide",
                tuple(guidance["questions"]),
                branch,
                worktree,
            )

        if not skip_implementation:
            runtime["stage"] = "implementing"
            state["active_run"]["stage"] = "implementing"
            store.save(state)
            events.emit(
                "agent_started",
                run_id=run_id,
                task_id=task.id,
                phase="implementing",
                outcome="started",
                details=self._profile_dict(workflow, task.agent_profile),
            )
            self._run_agent_guarded(
                git,
                agent,
                AgentRequest(
                    role="implementer",
                    profile=workflow.model_profiles[task.agent_profile],
                    prompt=implement_prompt(workflow, task, guidance),
                    cwd=worktree,
                    run_dir=run_dir,
                ),
                workflow.turn_timeout_seconds,
            )

        commands = self._verification_commands(workflow, task)
        while True:
            self._assert_agent_git_integrity(git, worktree, branch, start_commit, task.id)
            runtime["stage"] = "verifying"
            runtime["repair_cycles"] = repairs
            state["active_run"]["stage"] = "verifying"
            store.save(state)
            cycle_dir = run_dir / ("cycle-%02d" % repairs)
            results, summary, tree_digest = self._verify_stable(
                workflow, task, git, verifier, worktree, start_commit, cycle_dir
            )
            passed = all(result.passed for result in results)
            events.emit(
                "verification_completed",
                run_id=run_id,
                task_id=task.id,
                phase="verifying",
                outcome="passed" if passed else "failed",
                details={"tree_digest": tree_digest, "repair_cycle": repairs},
            )
            if not passed:
                feedback = "Deterministic verification failed:\n\n" + summary
            else:
                runtime["stage"] = "reviewing"
                state["active_run"]["stage"] = "reviewing"
                store.save(state)
                review_response = self._run_agent_guarded(
                    git,
                    agent,
                    AgentRequest(
                        role="reviewer",
                        profile=workflow.model_profiles["reviewer"],
                        prompt=review_prompt(workflow, task, guidance, start_commit, summary),
                        cwd=worktree,
                        run_dir=cycle_dir,
                        response_schema=REVIEW_SCHEMA,
                    ),
                    workflow.turn_timeout_seconds,
                )
                review = review_response.output
                self._validate_review(review)
                (cycle_dir / "review.json").write_text(
                    json.dumps(review, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
                after_review_tree = git.stage_and_tree(worktree)
                self._assert_allowed_changes(workflow, task, git, worktree, start_commit)
                if after_review_tree != tree_digest:
                    raise GitSafetyError(
                        "E_REVIEW_MUTATED_TREE", "Read-only review changed the evidence tree"
                    )
                verdict = review["verdict"]
                events.emit(
                    "review_completed",
                    run_id=run_id,
                    task_id=task.id,
                    phase="reviewing",
                    outcome=verdict,
                    details={"tree_digest": tree_digest, "repair_cycle": repairs},
                )
                if verdict == "accept":
                    self._assert_agent_git_integrity(
                        git, worktree, branch, start_commit, task.id
                    )
                    accepted_tree = git.stage_and_tree(worktree)
                    self._assert_allowed_changes(workflow, task, git, worktree, start_commit)
                    if accepted_tree != tree_digest:
                        raise GitSafetyError(
                            "E_EVIDENCE_STALE", "Worktree changed after review acceptance"
                        )
                    intent = self._checkpoint_intent(
                        task, workflow, start_commit, tree_digest, "agent"
                    )
                    runtime["checkpoint_intent"] = intent
                    runtime["stage"] = "checkpointing"
                    state["active_run"]["stage"] = "checkpointing"
                    store.save(state)
                    commit = git.commit_task(
                        worktree,
                        branch,
                        start_commit,
                        tree_digest,
                        task.id,
                        task.title,
                    )
                    checkpoint = self._checkpoint_from_intent(intent, commit)
                    runtime.update(
                        {
                            "stage": "checkpointed",
                            "checkpoint": checkpoint,
                            "engine_commit": commit,
                            "reviewed_tree": tree_digest,
                            "updated_at": utc_now(),
                        }
                    )
                    runtime.pop("checkpoint_intent", None)
                    state["active_run"]["stage"] = "checkpointed"
                    store.save(state)
                    integrated_commit = git.integrate_fast_forward(
                        integration_worktree, branch
                    )
                    self._accept_task(
                        state,
                        task,
                        integrated_commit,
                        branch,
                        worktree,
                        repair_cycles=repairs,
                    )
                    state.setdefault("runs", []).append(
                        {
                            "run_id": run_id,
                            "task_id": task.id,
                            "status": "accepted",
                            "commit": commit,
                            "tree_digest": tree_digest,
                            "repair_cycles": repairs,
                            "completed_at": utc_now(),
                        }
                    )
                    store.save(state)
                    events.emit(
                        "run_completed",
                        run_id=run_id,
                        task_id=task.id,
                        phase="finishing",
                        outcome="accepted",
                        details={
                            "commit": commit,
                            "integration_commit": integrated_commit,
                            "tree_digest": tree_digest,
                            "repair_cycles": repairs,
                        },
                    )
                    return RunOutcome(
                        status="accepted",
                        summary="Accepted %s after %d repair cycle(s)." % (task.id, repairs),
                        task_id=task.id,
                        run_id=run_id,
                        branch=branch,
                        worktree=str(worktree),
                        repair_cycles=repairs,
                        details={
                            "commit": commit,
                            "integration_commit": integrated_commit,
                            "tree_digest": tree_digest,
                            "evidence": str(run_dir),
                        },
                    )
                if verdict == "needs_human":
                    return self._block_for_human(
                        state,
                        store,
                        events,
                        task,
                        run_id,
                        "review",
                        tuple(review["questions"]),
                        branch,
                        worktree,
                    )
                if verdict == "reject":
                    raise RunFailed(
                        "E_REVIEW_REJECTED",
                        "Reviewer rejected task %s: %s" % (task.id, review["summary"]),
                    )
                feedback = "Reviewer requested repair:\n\n" + json.dumps(
                    review["findings"], indent=2, sort_keys=True
                )

            if repairs >= workflow.max_repair_cycles:
                raise RunFailed(
                    "E_REPAIR_EXHAUSTED",
                    "Task %s exhausted %d repair cycles"
                    % (task.id, workflow.max_repair_cycles),
                )
            repairs += 1
            runtime["stage"] = "repairing"
            runtime["repair_cycles"] = repairs
            state["active_run"]["stage"] = "repairing"
            store.save(state)
            events.emit(
                "repair_started",
                run_id=run_id,
                task_id=task.id,
                phase="repairing",
                outcome="started",
                details={"repair_cycle": repairs},
            )
            self._run_agent_guarded(
                git,
                agent,
                AgentRequest(
                    role="implementer",
                    profile=workflow.model_profiles[task.agent_profile],
                    prompt=repair_prompt(workflow, task, guidance, feedback, repairs),
                    cwd=worktree,
                    run_dir=run_dir / ("repair-%02d" % repairs),
                ),
                workflow.turn_timeout_seconds,
            )

    def _verify_stable(
        self,
        workflow: Workflow,
        task: Task,
        git: GitRepository,
        verifier: Verifier,
        worktree: Path,
        start_commit: str,
        evidence_dir: Path,
    ) -> Tuple[Sequence[VerificationResult], str, str]:
        commands = self._verification_commands(workflow, task)
        pass_payloads: List[Mapping[str, Any]] = []
        last_results: Sequence[VerificationResult] = ()
        last_summary = ""
        last_tree = ""
        for pass_number in range(1, _MAX_VERIFICATION_STABILITY_PASSES + 1):
            before_tree = git.stage_and_tree(worktree)
            self._assert_allowed_changes(workflow, task, git, worktree, start_commit)
            pass_dir = evidence_dir / ("pass-%02d" % pass_number)
            results = self._guard_repository_action(
                git,
                "verification",
                lambda: verifier.run(
                    commands, worktree, pass_dir, workflow.command_timeout_seconds
                ),
            )
            after_tree = git.stage_and_tree(worktree)
            self._assert_allowed_changes(workflow, task, git, worktree, start_commit)
            summary = verification_summary(results)
            stable = before_tree == after_tree
            pass_payloads.append(
                {
                    "pass": pass_number,
                    "before_tree": before_tree,
                    "after_tree": after_tree,
                    "stable": stable,
                    "commands": [
                        {
                            "command": result.command,
                            "exit_code": result.exit_code,
                            "duration_seconds": result.duration_seconds,
                            "stdout": str(result.stdout_path),
                            "stderr": str(result.stderr_path),
                        }
                        for result in results
                    ],
                }
            )
            last_results, last_summary, last_tree = results, summary, after_tree
            if stable:
                evidence_dir.mkdir(parents=True, exist_ok=True)
                (evidence_dir / "verification.json").write_text(
                    json.dumps(
                        {"tree_digest": after_tree, "stability_passes": pass_payloads},
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return results, summary, after_tree
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "verification.json").write_text(
            json.dumps(
                {"tree_digest": last_tree, "stability_passes": pass_payloads},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        raise RunFailed(
            "E_VERIFY_UNSTABLE",
            "Verification changed the candidate tree on all %d stability passes"
            % _MAX_VERIFICATION_STABILITY_PASSES,
        )

    def _context(self) -> Tuple[Workflow, Plan, GitRepository, StateStore, EventLog]:
        workflow = load_workflow(self.workflow_path, self.repo_root)
        plan = load_plan(workflow.plan_path, workflow)
        git = GitRepository(self.repo_root, timeout_seconds=workflow.command_timeout_seconds)
        return workflow, plan, git, StateStore(workflow.state_path), EventLog(workflow.run_root)

    def _agent(self, workflow: Workflow) -> AgentPort:
        if self._injected_agent is not None:
            return self._injected_agent
        return CodexCliAdapter(strip_environment=workflow.strip_environment)

    @staticmethod
    def _reconcile_child_processes(workflow: Workflow) -> None:
        Verifier(workflow.strip_environment).reconcile(workflow.run_root)

    def _policy_paths(self, workflow: Workflow) -> List[str]:
        paths = [self._relative(workflow.path), self._relative(workflow.plan_path)]
        paths.extend(workflow.policy_inputs)
        return list(dict.fromkeys(paths))

    def _preflight_task(
        self, workflow: Workflow, task: Task, git: GitRepository, base_ref: str
    ) -> str:
        git.validate_repository()
        base_commit = git.resolve_ref(base_ref)
        policy_paths = self._policy_paths(workflow)
        required = list(dict.fromkeys(policy_paths + list(task.source_paths)))
        for path in required:
            self._validate_relative_source(path)
            if not git.path_exists_at(base_ref, path):
                raise GitSafetyError(
                    "E_SOURCE_NOT_IN_BASE",
                    "%s is not present in pinned base %s (%s)"
                    % (path, base_ref, base_commit[:12]),
                    details={"path": path, "base_ref": base_ref, "base_commit": base_commit},
                )
        dirty = git.dirty_paths(required)
        if dirty:
            raise GitSafetyError(
                "E_DIRTY_POLICY_INPUT",
                "Commit or restore run inputs before starting: %s" % ", ".join(dirty),
                details={"paths": dirty},
            )
        if base_ref != "HEAD":
            result = git.run(["diff", "--quiet", base_ref, "--"] + policy_paths, check=False)
            if result.returncode != 0:
                raise GitSafetyError(
                    "E_PLAN_STALE",
                    "WORKFLOW.md, PLAN.yaml, or policy inputs differ from %s" % base_ref,
                )
        return base_commit

    def _preflight_models(
        self, workflow: Workflow, task: Task, git: GitRepository
    ) -> Mapping[str, Any]:
        agent = self._agent(workflow)
        catalog = self._guard_repository_action(
            git, "model capability discovery", agent.capabilities
        )
        self._validate_catalog_shape(catalog)
        selected: Dict[str, Any] = {}
        for profile_name in ("guide", task.agent_profile, "reviewer"):
            profile = workflow.model_profiles[profile_name]
            capability = catalog.get(profile.model)
            if not isinstance(capability, Mapping):
                raise AgentError(
                    "E_MODEL_UNAVAILABLE",
                    "%s is unavailable for required profile %s"
                    % (profile.model, profile_name),
                )
            efforts = capability.get("reasoning_efforts")
            if (
                not isinstance(efforts, Sequence)
                or isinstance(efforts, str)
                or profile.reasoning_effort not in efforts
            ):
                raise AgentError(
                    "E_REASONING_UNAVAILABLE",
                    "%s does not support %s reasoning for profile %s"
                    % (profile.model, profile.reasoning_effort, profile_name),
                )
            selected[profile_name] = {
                **self._profile_dict(workflow, profile_name),
                "catalog": {
                    "reasoning_efforts": list(efforts),
                    "description": str(capability.get("description", "")),
                },
            }
        return selected

    @staticmethod
    def _validate_catalog_shape(catalog: Any) -> None:
        if not isinstance(catalog, Mapping):
            raise AgentError("E_MODEL_CATALOG", "Model capabilities must be a mapping")

    def _select_task(
        self, plan: Plan, state: Mapping[str, Any], requested_id: Optional[str]
    ) -> Optional[Task]:
        tasks = plan.by_id()
        active = state.get("active_run") or {}
        active_task_id = active.get("task_id")
        if active_task_id and state["tasks"].get(active_task_id, {}).get("status") == TASK_RUNNING:
            if requested_id and requested_id != active_task_id:
                raise LoopError(
                    "E_ACTIVE_RUN_CONFLICT",
                    "Task %s is already active; cannot start %s"
                    % (active_task_id, requested_id),
                )
            task = tasks.get(active_task_id)
            if task:
                return task

        if requested_id:
            task = tasks.get(requested_id)
            if not task:
                raise LoopError("E_TASK_NOT_FOUND", "Unknown task: %s" % requested_id)
            runtime = state["tasks"][task.id]
            if runtime.get("status") == TASK_ACCEPTED:
                raise LoopError("E_TASK_ALREADY_ACCEPTED", "%s is already accepted" % task.id)
            missing = [
                dependency
                for dependency in task.depends_on
                if state["tasks"][dependency].get("status") != TASK_ACCEPTED
            ]
            if missing:
                raise LoopError(
                    "E_TASK_DEPENDENCIES",
                    "%s is waiting on: %s" % (task.id, ", ".join(missing)),
                )
            if runtime.get("status") in {TASK_BLOCKED, TASK_FAILED}:
                raise LoopError(
                    "E_TASK_RETRY_REQUIRED",
                    "%s is %s; run retry first" % (task.id, runtime.get("status")),
                )
            return task

        candidates = []
        for task in plan.tasks:
            runtime = state["tasks"][task.id]
            if runtime.get("status") not in {TASK_PENDING, TASK_WAITING_HUMAN}:
                continue
            if all(
                state["tasks"][dependency].get("status") == TASK_ACCEPTED
                for dependency in task.depends_on
            ):
                candidates.append(task)
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: (item.priority, item.id))[0]

    def _wait_for_human_gate(
        self,
        workflow: Workflow,
        task: Task,
        git: GitRepository,
        store: StateStore,
        events: EventLog,
        state: MutableMapping[str, Any],
        integration_worktree: Path,
    ) -> RunOutcome:
        runtime = state["tasks"][task.id]
        expected_base = git.resolve_ref_at(integration_worktree, "HEAD")
        task_digest = self._task_digest(task)
        workflow_digest = self._workflow_digest(workflow)
        request = runtime.get("gate_request")
        if runtime.get("status") == TASK_WAITING_HUMAN and isinstance(request, Mapping):
            if (
                request.get("expected_base") != expected_base
                or request.get("task_digest") != task_digest
                or request.get("workflow_digest") != workflow_digest
            ):
                raise GitSafetyError("E_GATE_STALE", "Existing human gate request is stale")
        else:
            request = {
                "version": 1,
                "request_id": new_run_id(task.id + "-request"),
                "expected_base": expected_base,
                "task_digest": task_digest,
                "workflow_digest": workflow_digest,
                "issued_at": utc_now(),
            }
            runtime.update(
                {
                    "status": TASK_WAITING_HUMAN,
                    "stage": "waiting_human",
                    "updated_at": utc_now(),
                    "questions": [task.objective],
                    "integration_worktree": str(integration_worktree),
                    "gate_request": request,
                }
            )
            store.save(state)
            events.emit(
                "human_gate_waiting",
                task_id=task.id,
                phase="gate",
                outcome="needs_human",
                message=task.objective,
                details={
                    "request_id": request["request_id"],
                    "expected_base": expected_base,
                },
            )
        return RunOutcome(
            status="needs_human",
            summary="Human gate %s is ready for review." % task.id,
            task_id=task.id,
            worktree=str(integration_worktree),
            questions=(task.objective,),
            details={
                "request_id": request["request_id"],
                "expected_base": request["expected_base"],
            },
        )

    def _idle_outcome(self, plan: Plan, state: Mapping[str, Any]) -> RunOutcome:
        statuses = {task.id: state["tasks"][task.id].get("status") for task in plan.tasks}
        if all(status == TASK_ACCEPTED for status in statuses.values()):
            return RunOutcome(status="complete", summary="All plan tasks are accepted.")
        blocked = [
            task_id
            for task_id, status in statuses.items()
            if status in {TASK_BLOCKED, TASK_FAILED}
        ]
        if blocked:
            return RunOutcome(
                status="blocked",
                summary="No task is runnable. Retry or resolve: %s" % ", ".join(blocked),
                details={"blocked_tasks": blocked},
            )
        return RunOutcome(
            status="blocked",
            summary="No dependency-ready task is available.",
            details={"statuses": statuses},
        )

    def _block_for_human(
        self,
        state: MutableMapping[str, Any],
        store: StateStore,
        events: EventLog,
        task: Task,
        run_id: str,
        phase: str,
        questions: Tuple[str, ...],
        branch: str,
        worktree: Path,
    ) -> RunOutcome:
        runtime = state["tasks"][task.id]
        runtime.update(
            {
                "status": TASK_BLOCKED,
                "stage": "needs_human",
                "questions": list(questions),
                "updated_at": utc_now(),
            }
        )
        state["active_run"] = None
        store.save(state)
        events.emit(
            "run_needs_human",
            run_id=run_id,
            task_id=task.id,
            phase=phase,
            outcome="needs_human",
            details={"questions": list(questions)},
        )
        return RunOutcome(
            status="needs_human",
            summary="Task %s needs a human decision." % task.id,
            task_id=task.id,
            run_id=run_id,
            branch=branch,
            worktree=str(worktree),
            questions=questions,
        )

    @staticmethod
    def _validate_guide(value: Any, task: Task) -> None:
        expected = {
            "decision",
            "summary",
            "implementation_steps",
            "risks",
            "acceptance_checks",
            "questions",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise AgentError("E_AGENT_OUTPUT", "Guide output has missing or extra fields")
        if value["decision"] not in {"proceed", "needs_human"} or not isinstance(
            value["summary"], str
        ):
            raise AgentError("E_AGENT_OUTPUT", "Guide decision or summary is invalid")
        for key in ("implementation_steps", "risks", "questions"):
            if not isinstance(value[key], list) or any(
                not isinstance(item, str) for item in value[key]
            ):
                raise AgentError("E_AGENT_OUTPUT", "Guide %s must be a string list" % key)
        if not isinstance(value["acceptance_checks"], list):
            raise AgentError("E_AGENT_OUTPUT", "Guide acceptance_checks must be a list")
        criteria = []
        for check in value["acceptance_checks"]:
            if (
                not isinstance(check, dict)
                or set(check) != {"criterion", "evidence"}
                or not isinstance(check["criterion"], str)
                or not isinstance(check["evidence"], str)
            ):
                raise AgentError("E_AGENT_OUTPUT", "Guide acceptance check is invalid")
            criteria.append(check["criterion"])
        if value["decision"] == "proceed" and Counter(criteria) != Counter(task.acceptance):
            raise AgentError(
                "E_AGENT_OUTPUT",
                "Guide must map every task acceptance criterion exactly once",
            )
        if value["decision"] == "needs_human" and not value["questions"]:
            raise AgentError("E_AGENT_OUTPUT", "Guide needs_human requires questions")

    @staticmethod
    def _validate_review(value: Any) -> None:
        expected = {"verdict", "summary", "findings", "questions"}
        if not isinstance(value, dict) or set(value) != expected:
            raise AgentError("E_AGENT_OUTPUT", "Review output has missing or extra fields")
        if value["verdict"] not in {"accept", "repair", "needs_human", "reject"}:
            raise AgentError("E_AGENT_OUTPUT", "Review verdict is invalid")
        if not isinstance(value["summary"], str):
            raise AgentError("E_AGENT_OUTPUT", "Review summary must be a string")
        if not isinstance(value["questions"], list) or any(
            not isinstance(item, str) for item in value["questions"]
        ):
            raise AgentError("E_AGENT_OUTPUT", "Review questions must be a string list")
        if not isinstance(value["findings"], list):
            raise AgentError("E_AGENT_OUTPUT", "Review findings must be a list")
        for finding in value["findings"]:
            if not isinstance(finding, dict) or set(finding) != {
                "severity",
                "criterion",
                "message",
                "repair",
            }:
                raise AgentError("E_AGENT_OUTPUT", "Review finding is invalid")
            if finding["severity"] not in {"blocking", "important", "minor"} or any(
                not isinstance(finding[key], str)
                for key in ("criterion", "message", "repair")
            ):
                raise AgentError("E_AGENT_OUTPUT", "Review finding fields are invalid")
        if value["verdict"] == "accept" and any(
            finding["severity"] == "blocking" for finding in value["findings"]
        ):
            raise AgentError("E_AGENT_OUTPUT", "Accept cannot include blocking findings")
        if value["verdict"] == "repair" and not value["findings"]:
            raise AgentError("E_AGENT_OUTPUT", "Repair verdict requires findings")
        if value["verdict"] == "needs_human" and not value["questions"]:
            raise AgentError("E_AGENT_OUTPUT", "needs_human verdict requires questions")

    @staticmethod
    def _verification_commands(workflow: Workflow, task: Task) -> Tuple[str, ...]:
        return tuple(dict.fromkeys(workflow.default_verification + task.verification))

    @staticmethod
    def _validate_gate_attestation(
        note: str, approver: str, decision: str
    ) -> Tuple[str, str]:
        note = note.strip()
        approver = approver.strip()
        if not note:
            raise LoopError(
                "E_GATE_NOTE_REQUIRED", "A non-empty %s note is required" % decision
            )
        if not approver or any(character in approver for character in "\r\n\0"):
            raise LoopError(
                "E_APPROVER_REQUIRED", "A single-line approver role or name is required"
            )
        return note, approver

    @staticmethod
    def _profile_dict(workflow: Workflow, name: str) -> Mapping[str, str]:
        profile = workflow.model_profiles[name]
        return {
            "profile": profile.name,
            "model": profile.model,
            "reasoning_effort": profile.reasoning_effort,
            "sandbox": profile.sandbox,
        }

    def _run_agent_guarded(
        self,
        git: GitRepository,
        agent: AgentPort,
        request: AgentRequest,
        timeout_seconds: int,
    ) -> Any:
        return self._guard_repository_action(
            git,
            "%s agent" % request.role,
            lambda: agent.run(request, timeout_seconds),
        )

    @staticmethod
    def _guard_repository_action(
        git: GitRepository, label: str, action: Callable[[], Any]
    ) -> Any:
        before = git.safety_snapshot()
        try:
            result = action()
        except BaseException as exc:
            after = git.safety_snapshot()
            changed = sorted(key for key in before if before.get(key) != after.get(key))
            if changed:
                raise GitSafetyError(
                    "E_REPOSITORY_MUTATION",
                    "%s changed protected repository state" % label,
                    details={"changed_snapshot_keys": changed},
                ) from exc
            raise
        after = git.safety_snapshot()
        changed = sorted(key for key in before if before.get(key) != after.get(key))
        if changed:
            raise GitSafetyError(
                "E_REPOSITORY_MUTATION",
                "%s changed protected repository state" % label,
                details={"changed_snapshot_keys": changed},
            )
        return result

    @staticmethod
    def _assert_agent_git_integrity(
        git: GitRepository,
        worktree: Path,
        branch: str,
        start_commit: str,
        task_id: str,
    ) -> None:
        if git.current_branch(worktree) != branch:
            raise GitSafetyError("E_AGENT_GIT_MUTATION", "Agent switched the task branch")
        if git.resolve_ref_at(worktree, "HEAD") != start_commit:
            raise GitSafetyError(
                "E_AGENT_GIT_MUTATION",
                "Agent created or changed commits for task %s" % task_id,
            )

    def _assert_allowed_changes(
        self,
        workflow: Workflow,
        task: Task,
        git: GitRepository,
        worktree: Path,
        start_commit: str,
    ) -> None:
        changed = git.changed_paths(worktree, start_commit)
        protected = set(self._policy_paths(workflow))
        violations = [
            path
            for path in changed
            if path in protected
            or not any(fnmatch.fnmatch(path, pattern) for pattern in task.allowed_paths)
        ]
        if violations:
            raise GitSafetyError(
                "E_TASK_SCOPE_VIOLATION",
                "Task %s changed paths outside its contract: %s"
                % (task.id, ", ".join(sorted(violations))),
                details={"allowed_paths": list(task.allowed_paths), "violations": violations},
            )
        unsafe = git.unsafe_index_paths(worktree, changed)
        if unsafe:
            raise GitSafetyError(
                "E_UNSAFE_FILE_MODE",
                "Task %s created non-regular index entries: %s"
                % (task.id, ", ".join(sorted(unsafe))),
                details={"paths": unsafe},
            )

    @staticmethod
    def _accept_task(
        state: MutableMapping[str, Any],
        task: Task,
        commit: str,
        branch: str,
        worktree: Path,
        repair_cycles: int,
    ) -> None:
        state["tasks"][task.id].update(
            {
                "status": TASK_ACCEPTED,
                "stage": "accepted",
                "commit": commit,
                "branch": branch,
                "worktree": str(worktree),
                "repair_cycles": repair_cycles,
                "questions": [],
                "updated_at": utc_now(),
            }
        )
        state["active_run"] = None

    def _reconcile_accepted(
        self,
        state: MutableMapping[str, Any],
        plan: Plan,
        git: GitRepository,
        workflow: Workflow,
    ) -> bool:
        changed = False
        if not git.branch_exists(workflow.integration_branch):
            integration_head = None
        else:
            integration_head = git.resolve_ref(workflow.integration_branch)
        for task in plan.tasks:
            runtime = state["tasks"][task.id]
            if not isinstance(runtime.get("checkpoint"), Mapping):
                intent = runtime.get("approval_intent")
                if integration_head and isinstance(intent, Mapping):
                    checkpoint = self._checkpoint_from_valid_intent(
                        intent, task, workflow, git, integration_head, "human"
                    )
                    if checkpoint is not None:
                        runtime["checkpoint"] = checkpoint
                        runtime.pop("approval_intent", None)
                        runtime["approval"] = {
                            "request_id": intent.get("request_id"),
                            "approver": intent.get("approver"),
                            "note": intent.get("note"),
                            "base_commit": intent.get("base_commit"),
                            "tree_digest": intent.get("reviewed_tree"),
                            "commit": integration_head,
                            "approved_at": utc_now(),
                        }
                        if not any(
                            isinstance(decision, Mapping)
                            and decision.get("request_id") == intent.get("request_id")
                            and decision.get("decision") == "approved"
                            for decision in runtime.get("gate_decisions", [])
                        ):
                            runtime.setdefault("gate_decisions", []).append(
                                {
                                    "request_id": intent.get("request_id"),
                                    "decision": "approved",
                                    "approver": intent.get("approver"),
                                    "note": intent.get("note"),
                                    "base_commit": intent.get("base_commit"),
                                    "tree_digest": intent.get("reviewed_tree"),
                                    "commit": integration_head,
                                    "decided_at": utc_now(),
                                }
                            )
                        changed = True
            checkpoint = runtime.get("checkpoint")
            valid = False
            if integration_head and isinstance(checkpoint, Mapping):
                valid = self._checkpoint_valid(
                    checkpoint, task, workflow, git, require_ancestor=integration_head
                )
            if valid:
                if runtime.get("status") != TASK_ACCEPTED or runtime.get("stage") != "accepted":
                    runtime.update(
                        {
                            "status": TASK_ACCEPTED,
                            "stage": "accepted",
                            "commit": checkpoint["engine_commit"],
                            "updated_at": utc_now(),
                        }
                    )
                    if (state.get("active_run") or {}).get("task_id") == task.id:
                        state["active_run"] = None
                    changed = True
            elif runtime.get("status") == TASK_ACCEPTED:
                runtime.update(
                    {
                        "status": TASK_BLOCKED,
                        "stage": "acceptance_stale",
                        "error": {
                            "code": "E_ACCEPTANCE_STALE",
                            "message": "Persisted acceptance no longer matches policy and Git evidence",
                            "details": {},
                            "exit_code": 30,
                        },
                        "updated_at": utc_now(),
                    }
                )
                changed = True
        return changed

    def _checkpoint_intent(
        self,
        task: Task,
        workflow: Workflow,
        base_commit: str,
        reviewed_tree: str,
        kind: str,
    ) -> Dict[str, Any]:
        return {
            "version": _CHECKPOINT_VERSION,
            "kind": kind,
            "task_digest": self._task_digest(task),
            "workflow_digest": self._workflow_digest(workflow),
            "base_commit": base_commit,
            "reviewed_tree": reviewed_tree,
            "recorded_at": utc_now(),
        }

    @staticmethod
    def _checkpoint_from_intent(intent: Mapping[str, Any], commit: str) -> Dict[str, Any]:
        return {
            "version": intent.get("version"),
            "kind": intent.get("kind"),
            "task_digest": intent.get("task_digest"),
            "workflow_digest": intent.get("workflow_digest"),
            "base_commit": intent.get("base_commit"),
            "reviewed_tree": intent.get("reviewed_tree"),
            "engine_commit": commit,
            "recorded_at": utc_now(),
        }

    def _recoverable_checkpoint(
        self,
        runtime: MutableMapping[str, Any],
        task: Task,
        workflow: Workflow,
        git: GitRepository,
        branch_head: str,
        expected_kind: str,
    ) -> Optional[Mapping[str, Any]]:
        checkpoint = runtime.get("checkpoint")
        if isinstance(checkpoint, Mapping) and self._checkpoint_valid(
            checkpoint, task, workflow, git
        ):
            if checkpoint.get("kind") == expected_kind and checkpoint.get("engine_commit") == branch_head:
                return checkpoint
        intent = runtime.get("checkpoint_intent")
        if isinstance(intent, Mapping):
            return self._checkpoint_from_valid_intent(
                intent, task, workflow, git, branch_head, expected_kind
            )
        return None

    def _checkpoint_from_valid_intent(
        self,
        intent: Mapping[str, Any],
        task: Task,
        workflow: Workflow,
        git: GitRepository,
        commit: str,
        expected_kind: str,
    ) -> Optional[Mapping[str, Any]]:
        if (
            intent.get("version") != _CHECKPOINT_VERSION
            or intent.get("kind") != expected_kind
            or intent.get("task_digest") != self._task_digest(task)
            or intent.get("workflow_digest") != self._workflow_digest(workflow)
            or not isinstance(intent.get("base_commit"), str)
            or not isinstance(intent.get("reviewed_tree"), str)
        ):
            return None
        try:
            if (
                git.commit_parent(commit) != intent["base_commit"]
                or git.commit_tree(commit) != intent["reviewed_tree"]
            ):
                return None
        except LoopError:
            return None
        return self._checkpoint_from_intent(intent, commit)

    def _checkpoint_valid(
        self,
        checkpoint: Mapping[str, Any],
        task: Task,
        workflow: Workflow,
        git: GitRepository,
        require_ancestor: Optional[str] = None,
    ) -> bool:
        if (
            checkpoint.get("version") != _CHECKPOINT_VERSION
            or checkpoint.get("kind") not in {"agent", "human"}
            or checkpoint.get("task_digest") != self._task_digest(task)
            or checkpoint.get("workflow_digest") != self._workflow_digest(workflow)
            or not isinstance(checkpoint.get("base_commit"), str)
            or not isinstance(checkpoint.get("reviewed_tree"), str)
            or not isinstance(checkpoint.get("engine_commit"), str)
        ):
            return False
        try:
            commit = checkpoint["engine_commit"]
            if (
                git.commit_parent(commit) != checkpoint["base_commit"]
                or git.commit_tree(commit) != checkpoint["reviewed_tree"]
            ):
                return False
            if require_ancestor and not git.is_ancestor(commit, require_ancestor):
                return False
        except LoopError:
            return False
        return True

    @staticmethod
    def _task_digest(task: Task) -> str:
        value = json.dumps(
            task_to_prompt_dict(task), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(value).hexdigest()

    def _workflow_digest(self, workflow: Workflow) -> str:
        digest = hashlib.sha256()
        for relative in self._policy_paths(workflow):
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            path = self.repo_root / relative
            try:
                digest.update(path.read_bytes())
            except OSError as exc:
                digest.update(("missing:%s" % exc.errno).encode("ascii"))
            digest.update(b"\0")
        return digest.hexdigest()

    @staticmethod
    def _validated_run_id(value: Any) -> str:
        if not isinstance(value, str) or not value or Path(value).name != value:
            raise GitSafetyError("E_ACTIVE_RUN_STATE", "Active run id is unsafe")
        return value

    def _relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.repo_root).as_posix()
        except ValueError:
            raise GitSafetyError("E_WORKTREE_ESCAPE", "%s is outside repository" % path)

    @staticmethod
    def _validate_relative_source(path: str) -> None:
        value = Path(path)
        if value.is_absolute() or ".." in value.parts or path.startswith(".git/"):
            raise GitSafetyError("E_SOURCE_PATH", "Unsafe source path: %s" % path)

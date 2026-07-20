from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple

import yaml

from .errors import ConfigError, PlanError
from .git_ops import workspace_key
from .models import ModelProfile, Plan, Task, Workflow


_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_ALLOWED_SANDBOXES = {"read-only", "workspace-write"}
_ALLOWED_MODES = {"agent", "human"}


def _git_branch_valid(value: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "check-ref-format", "--branch", value],
            text=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConfigError(
            "E_WORKFLOW_INVALID", "Cannot validate Git branch configuration: %s" % exc
        )
    return result.returncode == 0


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigError("E_WORKFLOW_INVALID", "%s must be a mapping" % label)
    return value


def _positive_int(value: Any, label: str, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError("E_WORKFLOW_INVALID", "%s must be a positive integer" % label)
    return value


def _string_list(value: Any, label: str, default: Sequence[str] = ()) -> Tuple[str, ...]:
    if value is None:
        return tuple(default)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ConfigError("E_WORKFLOW_INVALID", "%s must be a list of non-empty strings" % label)
    return tuple(item.strip() for item in value)


def _repo_path(repo_root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("E_WORKFLOW_INVALID", "%s must be a non-empty path" % label)
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(repo_root)
    except ValueError:
        raise ConfigError(
            "E_WORKTREE_ESCAPE",
            "%s must stay inside the repository: %s" % (label, candidate),
            exit_code=30,
        )
    return candidate


def split_workflow(path: Path) -> Tuple[Mapping[str, Any], str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError("E_WORKFLOW_MISSING", "Cannot read workflow %s: %s" % (path, exc))

    if not text.startswith("---"):
        return {}, text.strip()

    lines = text.splitlines()
    closing = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing = index
            break
    if closing is None:
        raise ConfigError("E_WORKFLOW_INVALID", "WORKFLOW.md front matter has no closing ---")

    try:
        loaded = yaml.safe_load("\n".join(lines[1:closing])) or {}
    except yaml.YAMLError as exc:
        raise ConfigError("E_WORKFLOW_INVALID", "Invalid WORKFLOW.md YAML: %s" % exc)
    if not isinstance(loaded, Mapping):
        raise ConfigError("E_WORKFLOW_INVALID", "WORKFLOW.md front matter must be a mapping")
    return loaded, "\n".join(lines[closing + 1 :]).strip()


def load_workflow(path: Path, repo_root: Path) -> Workflow:
    path = path.resolve()
    repo_root = repo_root.resolve()
    config, prompt = split_workflow(path)
    loop = _mapping(config.get("loop", {}), "loop")
    model_values = _mapping(config.get("models", {}), "models")
    verification = _mapping(config.get("verification", {}), "verification")
    security = _mapping(config.get("security", {}), "security")

    profiles: Dict[str, ModelProfile] = {}
    for name, raw in model_values.items():
        profile = _mapping(raw, "models.%s" % name)
        model = profile.get("model")
        effort = profile.get("reasoning_effort")
        sandbox = profile.get("sandbox")
        if not isinstance(model, str) or not model.strip():
            raise ConfigError("E_WORKFLOW_INVALID", "models.%s.model is required" % name)
        if not isinstance(effort, str) or not effort.strip():
            raise ConfigError("E_WORKFLOW_INVALID", "models.%s.reasoning_effort is required" % name)
        if sandbox not in _ALLOWED_SANDBOXES:
            raise ConfigError(
                "E_WORKFLOW_INVALID",
                "models.%s.sandbox must be read-only or workspace-write" % name,
            )
        profiles[str(name)] = ModelProfile(str(name), model.strip(), effort.strip(), sandbox)

    required_profiles = {"guide", "implementer", "reviewer"}
    missing = sorted(required_profiles - set(profiles))
    if missing:
        raise ConfigError("E_WORKFLOW_INVALID", "Missing model profiles: %s" % ", ".join(missing))
    if profiles["guide"].sandbox != "read-only" or profiles["reviewer"].sandbox != "read-only":
        raise ConfigError("E_WORKFLOW_INVALID", "guide and reviewer profiles must be read-only")
    for name, profile in profiles.items():
        if name.startswith("implementer") and profile.sandbox != "workspace-write":
            raise ConfigError("E_WORKFLOW_INVALID", "%s must use workspace-write" % name)

    integration_branch = str(loop.get("integration_branch", "codex/loop-integration"))
    branch_prefix = str(loop.get("task_branch_prefix", "codex/loop-"))
    if (
        not _BRANCH.match(integration_branch)
        or not _BRANCH.match(branch_prefix)
        or not _git_branch_valid(integration_branch)
        or not _git_branch_valid(branch_prefix + "probe")
    ):
        raise ConfigError("E_WORKFLOW_INVALID", "Configured branch names contain unsafe characters")
    if integration_branch == "main":
        raise ConfigError(
            "E_WORKFLOW_INVALID",
            "loop.integration_branch must be an isolated branch, not main",
        )
    if not integration_branch.startswith("codex/") or not branch_prefix.startswith("codex/"):
        raise ConfigError(
            "E_WORKFLOW_INVALID",
            "Integration and task branches must stay under the codex/ namespace",
        )

    plan_path = _repo_path(repo_root, loop.get("plan_path", "PLAN.yaml"), "loop.plan_path")
    state_path = _repo_path(repo_root, loop.get("state_path", ".loop/state.json"), "loop.state_path")
    run_root = _repo_path(repo_root, loop.get("run_root", ".loop/runs"), "loop.run_root")
    workspace_root = _repo_path(
        repo_root, loop.get("workspace_root", ".loop/worktrees"), "loop.workspace_root"
    )
    for label, runtime_path in (
        ("loop.state_path", state_path),
        ("loop.run_root", run_root),
        ("loop.workspace_root", workspace_root),
    ):
        relative = runtime_path.relative_to(repo_root)
        if runtime_path == repo_root or (relative.parts and relative.parts[0] == ".git"):
            raise ConfigError(
                "E_WORKFLOW_INVALID",
                "%s must not be the repository root or inside .git" % label,
                exit_code=30,
            )
    if run_root == workspace_root:
        raise ConfigError(
            "E_WORKFLOW_INVALID",
            "loop.run_root and loop.workspace_root must be distinct",
            exit_code=30,
        )
    event_path = run_root.parent / "events.jsonl"
    lock_path = state_path.with_suffix(state_path.suffix + ".lock")

    def overlaps(left: Path, right: Path) -> bool:
        try:
            left.relative_to(right)
            return True
        except ValueError:
            pass
        try:
            right.relative_to(left)
            return True
        except ValueError:
            return False

    if (
        overlaps(run_root, workspace_root)
        or overlaps(state_path, event_path)
        or overlaps(lock_path, event_path)
        or overlaps(lock_path, run_root)
        or overlaps(lock_path, workspace_root)
        or overlaps(lock_path, state_path)
        or overlaps(event_path, run_root)
        or overlaps(event_path, workspace_root)
        or state_path == run_root
        or state_path == workspace_root
        or _path_within(state_path, run_root)
        or _path_within(state_path, workspace_root)
        or _path_within(run_root, state_path)
        or _path_within(workspace_root, state_path)
    ):
        raise ConfigError(
            "E_WORKFLOW_INVALID",
            "State, event, run, and worktree runtime paths must not overlap",
            exit_code=30,
        )
    keep_worktrees = loop.get("keep_worktrees", True)
    if not isinstance(keep_worktrees, bool):
        raise ConfigError(
            "E_WORKFLOW_INVALID", "loop.keep_worktrees must be a boolean"
        )
    if keep_worktrees is not True:
        raise ConfigError(
            "E_WORKFLOW_INVALID",
            "This local profile preserves worktrees; loop.keep_worktrees=false is not implemented",
        )

    return Workflow(
        path=path,
        repo_root=repo_root,
        plan_path=plan_path,
        state_path=state_path,
        run_root=run_root,
        workspace_root=workspace_root,
        integration_branch=integration_branch,
        task_branch_prefix=branch_prefix,
        max_repair_cycles=_positive_int(loop.get("max_repair_cycles"), "loop.max_repair_cycles", 3),
        turn_timeout_seconds=_positive_int(
            loop.get("turn_timeout_seconds"), "loop.turn_timeout_seconds", 3600
        ),
        command_timeout_seconds=_positive_int(
            loop.get("command_timeout_seconds"), "loop.command_timeout_seconds", 900
        ),
        keep_worktrees=keep_worktrees,
        policy_inputs=_string_list(loop.get("policy_inputs"), "loop.policy_inputs"),
        default_verification=_string_list(
            verification.get("default_commands"),
            "verification.default_commands",
            ("git diff --check",),
        ),
        strip_environment=_string_list(
            security.get("strip_environment"), "security.strip_environment"
        ),
        model_profiles=profiles,
        prompt_policy=prompt,
    )


def _path_within(path: Path, parent: Path) -> bool:
    if path == parent:
        return True
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def load_plan(path: Path, workflow: Workflow) -> Plan:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PlanError("E_PLAN_REQUIRED", "Cannot read plan %s: %s" % (path, exc))
    except yaml.YAMLError as exc:
        raise PlanError("E_PLAN_INVALID", "Invalid plan YAML: %s" % exc)
    if not isinstance(raw, Mapping):
        raise PlanError("E_PLAN_INVALID", "PLAN.yaml must contain a mapping")

    version = raw.get("version")
    project = raw.get("project")
    task_values = raw.get("tasks")
    if version != 1:
        raise PlanError("E_PLAN_INVALID", "PLAN.yaml version must be 1")
    if not isinstance(project, str) or not project.strip():
        raise PlanError("E_PLAN_INVALID", "PLAN.yaml project is required")
    if not isinstance(task_values, list) or not task_values:
        raise PlanError("E_PLAN_INVALID", "PLAN.yaml tasks must be a non-empty list")

    tasks = []
    seen = set()
    for index, item in enumerate(task_values):
        if not isinstance(item, Mapping):
            raise PlanError("E_PLAN_INVALID", "tasks[%d] must be a mapping" % index)
        task_id = item.get("id")
        title = item.get("title")
        objective = item.get("objective")
        mode = item.get("mode", "agent")
        if not isinstance(task_id, str) or not _TASK_ID.match(task_id):
            raise PlanError("E_PLAN_INVALID", "tasks[%d].id is invalid" % index)
        if task_id in seen:
            raise PlanError("E_PLAN_INVALID", "Duplicate task id: %s" % task_id)
        seen.add(task_id)
        generated_branch = workflow.task_branch_prefix + workspace_key(task_id)
        if (
            not _git_branch_valid(generated_branch)
            or generated_branch == workflow.integration_branch
            or generated_branch.startswith(workflow.integration_branch + "/")
            or workflow.integration_branch.startswith(generated_branch + "/")
        ):
            raise PlanError(
                "E_PLAN_INVALID",
                "%s generates an invalid or colliding task branch %s"
                % (task_id, generated_branch),
            )
        if not isinstance(title, str) or not title.strip():
            raise PlanError("E_PLAN_INVALID", "%s.title is required" % task_id)
        if not isinstance(objective, str) or not objective.strip():
            raise PlanError("E_PLAN_INVALID", "%s.objective is required" % task_id)
        if mode not in _ALLOWED_MODES:
            raise PlanError("E_PLAN_INVALID", "%s.mode must be agent or human" % task_id)
        priority = item.get("priority", 100)
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise PlanError("E_PLAN_INVALID", "%s.priority must be an integer" % task_id)
        agent_profile = item.get("agent_profile", "implementer")
        if mode == "agent" and agent_profile not in workflow.model_profiles:
            raise PlanError(
                "E_PLAN_INVALID",
                "%s references unknown model profile %s" % (task_id, agent_profile),
            )
        if (
            mode == "agent"
            and agent_profile in workflow.model_profiles
            and workflow.model_profiles[str(agent_profile)].sandbox != "workspace-write"
        ):
            raise PlanError(
                "E_PLAN_INVALID",
                "%s agent profile %s must use workspace-write" % (task_id, agent_profile),
            )
        allowed_paths = _plan_string_list(item.get("allowed_paths", []), "%s.allowed_paths" % task_id)
        if mode == "agent" and not allowed_paths:
            raise PlanError("E_PLAN_INVALID", "%s.allowed_paths must not be empty" % task_id)
        tasks.append(
            Task(
                id=task_id,
                title=title.strip(),
                objective=objective.strip(),
                mode=mode,
                priority=priority,
                depends_on=_plan_string_list(item.get("depends_on", []), "%s.depends_on" % task_id),
                acceptance=_plan_string_list(item.get("acceptance", []), "%s.acceptance" % task_id),
                source_paths=_plan_string_list(item.get("source_paths", []), "%s.source_paths" % task_id),
                allowed_paths=allowed_paths,
                verification=_plan_string_list(item.get("verify", []), "%s.verify" % task_id),
                agent_profile=str(agent_profile),
            )
        )

    plan = Plan(version=version, project=project.strip(), tasks=tuple(tasks))
    _validate_dependencies(plan)
    return plan


def _plan_string_list(value: Any, label: str) -> Tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise PlanError("E_PLAN_INVALID", "%s must be a list of non-empty strings" % label)
    return tuple(item.strip() for item in value)


def _validate_dependencies(plan: Plan) -> None:
    tasks = plan.by_id()
    for task in plan.tasks:
        unknown = sorted(set(task.depends_on) - set(tasks))
        if unknown:
            raise PlanError(
                "E_PLAN_INVALID",
                "%s has unknown dependencies: %s" % (task.id, ", ".join(unknown)),
            )
        if task.id in task.depends_on:
            raise PlanError("E_PLAN_INVALID", "%s depends on itself" % task.id)

    visiting = set()
    visited = set()

    def visit(task_id: str) -> None:
        if task_id in visited:
            return
        if task_id in visiting:
            raise PlanError("E_PLAN_INVALID", "Dependency cycle includes %s" % task_id)
        visiting.add(task_id)
        for dependency in tasks[task_id].depends_on:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task in plan.tasks:
        visit(task.id)

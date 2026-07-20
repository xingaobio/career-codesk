from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


TASK_PENDING = "pending"
TASK_RUNNING = "running"
TASK_PAUSED = "paused"
TASK_WAITING_HUMAN = "waiting_human"
TASK_ACCEPTED = "accepted"
TASK_BLOCKED = "blocked"
TASK_FAILED = "failed"


@dataclass(frozen=True)
class ModelProfile:
    name: str
    model: str
    reasoning_effort: str
    sandbox: str


@dataclass(frozen=True)
class Workflow:
    path: Path
    repo_root: Path
    plan_path: Path
    state_path: Path
    run_root: Path
    workspace_root: Path
    integration_branch: str
    task_branch_prefix: str
    max_repair_cycles: int
    turn_timeout_seconds: int
    command_timeout_seconds: int
    keep_worktrees: bool
    policy_inputs: Tuple[str, ...]
    default_verification: Tuple[str, ...]
    strip_environment: Tuple[str, ...]
    model_profiles: Mapping[str, ModelProfile]
    prompt_policy: str


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    objective: str
    mode: str
    priority: int
    depends_on: Tuple[str, ...]
    acceptance: Tuple[str, ...]
    source_paths: Tuple[str, ...]
    allowed_paths: Tuple[str, ...]
    verification: Tuple[str, ...]
    agent_profile: str


@dataclass(frozen=True)
class Plan:
    version: int
    project: str
    tasks: Tuple[Task, ...]

    def by_id(self) -> Dict[str, Task]:
        return {task.id: task for task in self.tasks}


@dataclass(frozen=True)
class AgentRequest:
    role: str
    profile: ModelProfile
    prompt: str
    cwd: Path
    run_dir: Path
    response_schema: Optional[Mapping[str, Any]] = None
    session_path: Optional[Path] = None


@dataclass(frozen=True)
class AgentResponse:
    role: str
    output: Any
    last_message_path: Path
    stdout_path: Path
    stderr_path: Path


@dataclass(frozen=True)
class VerificationResult:
    command: str
    exit_code: int
    duration_seconds: float
    stdout_path: Path
    stderr_path: Path

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


@dataclass(frozen=True)
class RunOutcome:
    status: str
    summary: str
    task_id: Optional[str] = None
    run_id: Optional[str] = None
    branch: Optional[str] = None
    worktree: Optional[str] = None
    repair_cycles: int = 0
    questions: Tuple[str, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DoctorReport:
    structurally_valid: bool
    execution_ready: bool
    repo_root: str
    workflow_path: str
    plan_path: str
    models: Mapping[str, Mapping[str, str]]
    problems: Tuple[Mapping[str, Any], ...]
    warnings: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def task_to_prompt_dict(task: Task) -> Dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "objective": task.objective,
        "mode": task.mode,
        "priority": task.priority,
        "depends_on": list(task.depends_on),
        "acceptance": list(task.acceptance),
        "source_paths": list(task.source_paths),
        "allowed_paths": list(task.allowed_paths),
        "verification": list(task.verification),
        "agent_profile": task.agent_profile,
    }

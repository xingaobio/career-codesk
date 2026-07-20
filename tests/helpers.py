from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Mapping

from loop_engine.models import AgentRequest, AgentResponse


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(root),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), result.stderr))
    return result.stdout.strip()


def initialise_repo(root: Path, plan: str, workflow: str, source: str = "source\n") -> None:
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Test User")
    git(root, "config", "user.email", "test@example.invalid")
    (root / ".gitignore").write_text(".loop/\n__pycache__/\n", encoding="utf-8")
    (root / "WORKFLOW.md").write_text(workflow, encoding="utf-8")
    (root / "PLAN.yaml").write_text(plan, encoding="utf-8")
    (root / "source.md").write_text(source, encoding="utf-8")
    git(root, "add", ".gitignore", "WORKFLOW.md", "PLAN.yaml", "source.md")
    git(root, "commit", "-m", "initial")


MINIMAL_WORKFLOW = """---
loop:
  plan_path: PLAN.yaml
  state_path: .loop/state.json
  run_root: .loop/runs
  workspace_root: .loop/worktrees
  integration_branch: codex/loop-integration
  task_branch_prefix: codex/loop-
  max_repair_cycles: 2
  turn_timeout_seconds: 30
  command_timeout_seconds: 30
  policy_inputs:
    - source.md
models:
  guide:
    model: gpt-5.6-sol
    reasoning_effort: ultra
    sandbox: read-only
  implementer:
    model: gpt-5.6-terra
    reasoning_effort: high
    sandbox: workspace-write
  implementer_fast:
    model: gpt-5.6-luna
    reasoning_effort: high
    sandbox: workspace-write
  reviewer:
    model: gpt-5.6-sol
    reasoning_effort: ultra
    sandbox: read-only
verification:
  default_commands:
    - git diff --cached --check
---
Exploratory decisions require a human gate. Agents may not commit, merge, or push.
"""


MINIMAL_PLAN = """version: 1
project: Test project
tasks:
  - id: T001
    title: Produce verified output
    mode: agent
    priority: 10
    agent_profile: implementer
    depends_on: []
    objective: Write output.txt with the word fixed.
    acceptance:
      - output.txt contains fixed.
    source_paths:
      - source.md
    allowed_paths:
      - output.txt
    verify:
      - grep -q '^fixed$' output.txt
  - id: G001
    title: Approve output
    mode: human
    priority: 20
    depends_on:
      - T001
    objective: Change output.txt to approved and approve the gate.
    acceptance:
      - output.txt contains approved.
    source_paths:
      - output.txt
    allowed_paths:
      - output.txt
    verify:
      - grep -q '^approved$' output.txt
"""


class RepairingFakeAgent:
    def __init__(self) -> None:
        self.requests: List[AgentRequest] = []
        self.implementer_calls = 0

    def capabilities(self) -> Mapping[str, Mapping[str, Any]]:
        return {
            "gpt-5.6-sol": {"reasoning_efforts": ["ultra"]},
            "gpt-5.6-terra": {"reasoning_efforts": ["high"]},
            "gpt-5.6-luna": {"reasoning_efforts": ["high"]},
        }

    def run(self, request: AgentRequest, timeout_seconds: int) -> AgentResponse:
        self.requests.append(request)
        request.run_dir.mkdir(parents=True, exist_ok=True)
        artifact = request.run_dir / ("fake-%02d-%s.json" % (len(self.requests), request.role))
        stdout = artifact.with_suffix(".stdout")
        stderr = artifact.with_suffix(".stderr")
        stdout.write_text("{}\n", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")

        if request.role == "guide":
            output: Any = {
                "decision": "proceed",
                "summary": "Write and verify the requested file.",
                "implementation_steps": ["Write output.txt"],
                "risks": [],
                "acceptance_checks": [
                    {"criterion": "output.txt contains fixed.", "evidence": "grep command"}
                ],
                "questions": [],
            }
        elif request.role == "implementer":
            self.implementer_calls += 1
            value = "broken\n" if self.implementer_calls == 1 else "fixed\n"
            (request.cwd / "output.txt").write_text(value, encoding="utf-8")
            output = "implemented"
        elif request.role == "reviewer":
            output = {
                "verdict": "accept",
                "summary": "The verified tree satisfies the task.",
                "findings": [],
                "questions": [],
            }
        else:
            raise AssertionError("unexpected role %s" % request.role)
        artifact.write_text(json.dumps(output), encoding="utf-8")
        return AgentResponse(request.role, output, artifact, stdout, stderr)

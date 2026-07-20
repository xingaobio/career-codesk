from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from .models import Task, VerificationResult, Workflow, task_to_prompt_dict


def guide_prompt(
    workflow: Workflow,
    task: Task,
    base_commit: str,
    resolution_notes: Sequence[Mapping[str, Any]] = (),
) -> str:
    return """You are the high-level guide for one isolated Career CoDesk implementation run.

Model role: guide. You are read-only. Do not edit files, create commits, switch branches, merge, or push.

Repository policy:
%s

Pinned base commit: %s
Task contract:
%s

Recorded human resolutions from earlier blocked attempts:
%s

Start with the task's named source paths and only the portion of its allowed subtree needed by the acceptance criteria; do not inventory or reread the whole repository. Produce a bounded implementation plan and map every acceptance criterion to concrete evidence. The current product baseline is explicitly exploratory. If the task requires an unresolved product, legal, safeguarding, data-governance, or integration decision that the task contract does not authorize, return decision=needs_human with precise questions. Do not invent authority.
""" % (
        workflow.prompt_policy,
        base_commit,
        json.dumps(task_to_prompt_dict(task), indent=2, sort_keys=True),
        json.dumps(list(resolution_notes), indent=2, sort_keys=True),
    )


def implement_prompt(workflow: Workflow, task: Task, guidance: Mapping[str, Any]) -> str:
    return """You are the designer/implementer for one isolated Career CoDesk task.

You may edit files only in the current worktree. Do not create commits, switch branches, merge, push, modify remotes, or edit the caller's main worktree. Follow repository instructions and keep changes within this task.

Repository policy:
%s

Task contract:
%s

Approved high-level guidance:
%s

Implement the task completely. Keep context local: read the named source paths, relevant changed files, and focused test seams; avoid full logs and whole-repository rescans. Run focused checks while working. Preserve source-qualified facts and the documented human-approval boundaries. Finish with a concise summary of changes and checks; the engine will run the authoritative verification commands afterward.
""" % (
        workflow.prompt_policy,
        json.dumps(task_to_prompt_dict(task), indent=2, sort_keys=True),
        json.dumps(guidance, indent=2, sort_keys=True),
    )


def repair_prompt(
    workflow: Workflow,
    task: Task,
    guidance: Mapping[str, Any],
    feedback: str,
    repair_cycle: int,
) -> str:
    return """You are repairing an existing isolated implementation for Career CoDesk.

You may edit files only in the current worktree. Do not create commits, switch branches, merge, push, or broaden the task. This is repair cycle %d.

Task contract:
%s

High-level guidance:
%s

Authoritative failure/review evidence:
%s

Treat this as one consolidated repair, not a new audit. Fix only the blocking findings supplied above, including their shared root cause where necessary. Do not implement important/minor follow-ups or invent additional hardening scope. Re-run focused checks for the affected acceptance criteria and leave the worktree ready for deterministic verification. If the evidence exposes a missing human decision, explain it in your final message without inventing the decision.
""" % (
        repair_cycle,
        json.dumps(task_to_prompt_dict(task), indent=2, sort_keys=True),
        json.dumps(guidance, indent=2, sort_keys=True),
        feedback,
    )


def review_prompt(
    workflow: Workflow,
    task: Task,
    guidance: Mapping[str, Any],
    base_commit: str,
    verification: str,
) -> str:
    return """You are the independent high-level reviewer for one isolated Career CoDesk task.

Model role: reviewer. You are read-only. Do not edit files, create commits, switch branches, merge, or push.

Task contract:
%s

Guide plan:
%s

Pinned task base: %s
Deterministic verification evidence:
%s

Review only the task acceptance criteria and direct regressions introduced by this diff. Inspect the changed files plus the task source paths needed to decide those criteria; do not expand into a general architecture, adversarial-type, or future-hardening audit.

A blocking finding is allowed only when evidence shows that an exact acceptance criterion is false, or the diff directly violates one of these fixed run invariants:
- RUN-INVARIANT: task scope and repository policy
- RUN-INVARIANT: safety and data integrity

For an acceptance failure, copy the exact acceptance-criterion text into finding.criterion. For a run-invariant failure, use the exact label above. Consolidate shared root causes and return no more than six findings. Additional robustness tests, speculative attack variants, style improvements, and future architecture work are important/minor follow-ups: record them if useful, but they do not block delivery. If there are no blocking findings, verdict must be accept even when important/minor follow-ups remain. Use repair only for one or more blocking findings that code can fix within this task. Use needs_human when authority or a product decision is missing. Use reject only when at least one valid blocking finding exists and repair within this task is inappropriate.
""" % (
        json.dumps(task_to_prompt_dict(task), indent=2, sort_keys=True),
        json.dumps(guidance, indent=2, sort_keys=True),
        base_commit,
        verification,
    )

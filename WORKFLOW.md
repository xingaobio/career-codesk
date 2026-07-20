---
loop:
  plan_path: PLAN.yaml
  state_path: .loop/state.json
  run_root: .loop/runs
  workspace_root: .loop/worktrees
  integration_branch: codex/loop-integration
  task_branch_prefix: codex/loop-
  max_repair_cycles: 3
  turn_timeout_seconds: 3600
  command_timeout_seconds: 900
  keep_worktrees: true
  policy_inputs:
    - SPEC.md
    - README.md
    - product_definition.md
    - docs/versions/v0.1.0-early-product-concept.md
    - Adoption Rates of Triage and Digital Tracking Systems in UK FE Colleges.md
    - 英国学院职业发展痛点.md

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
    - python3 -m unittest discover -s tests -v

security:
  strip_environment:
    - GITHUB_TOKEN
    - GH_TOKEN
    - LINEAR_API_KEY
    - SLACK_BOT_TOKEN
    - ATLASSIAN_API_TOKEN
    - DATABASE_URL
---
# Career CoDesk engineering-loop policy

This workflow automates implementation work on Career CoDesk. It is inspired by the isolation,
repository-owned policy, reconciliation, bounded semantic repair, and observability requirements in
`SPEC.md`; it is a local implementation-run profile, not a claim of complete Symphony service
conformance.

## Model roles

- The guide and reviewer use `gpt-5.6-sol` with `ultra` reasoning and read-only access.
- Normal design and implementation use `gpt-5.6-terra` with `high` reasoning.
- `gpt-5.6-luna` with `high` reasoning is an explicit fast profile for low-risk documentation,
  fixtures, and mechanical tasks. It is never selected as a silent fallback.
- Deterministic commands, not an LLM, own verification.

## Product authority

The current `0.1.0-early` snapshot is exploratory and is not an approved implementation
specification. Agents MUST preserve it as history. The first implementation RFC may recommend
defaults, but substantive product work MUST remain behind the plan's human approval gate. Missing
authority is a `needs_human` outcome, not permission to invent a decision.

Until that gate is approved, assume only the following prototype boundary:

- synthetic learner data and CSV/mock inputs only;
- no real learner PII, SEND, medical, safeguarding, or welfare records;
- no live MIS connection, writeback, email, calendar, payment, deployment, or other external
  mutation;
- visible separation between source-qualified learner statements and provisional AI inference;
- deterministic code owns arithmetic, entitlement, capacity, and schedule feasibility;
- consequential routing always requires meaningful adviser approval;
- a safety or safeguarding-like signal exits the ordinary career workflow for restricted human
  handling and is never converted into a risk score;
- the product assists careers teams and does not replace Level 6 personal guidance, diagnose a
  learner, predict NEET status, or claim guaranteed Gatsby, Ofsted, or legal compliance.

## Run invariants

- Work only in the task worktree supplied as the current directory.
- Do not create commits, change branches, merge, push, open pull requests, deploy, or mutate remote
  systems. The run engine owns checkpoints and integration into its private `codex/*` branch.
- Do not edit `WORKFLOW.md`, `PLAN.yaml`, the loop engine, or a workflow `policy_input`. Other task
  source files are read-only unless the same path is explicitly listed in that task's
  `allowed_paths`; that narrow overlap authorises only the change described by the task.
- Stay inside the task's `allowed_paths` contract.
- Preserve evidence: original inputs, AI hypotheses, human decisions, delivery events, outcome
  confirmations, and writeback attempts are distinct records.
- Use a modular-monolith direction for the MVP. Do not introduce microservices, a broad chatbot,
  proprietary careers content, live multi-MIS integrations, or a provider marketplace.
- Tests and generated demo data must be deterministic and contain no real-person data.
- A reviewer may request repair only within the task contract. Scope changes and unresolved product
  choices return `needs_human`.

## Completion rule

A task is accepted only after all configured commands pass, the independent reviewer accepts the
exact evidence tree, the engine creates its own exact-tree task commit with hooks bypassed, and that
commit fast-forwards into the private integration branch. Acceptance is bound to persisted task,
workflow, base-commit, reviewed-tree, and engine-commit metadata; a commit-message trailer alone is
never acceptance evidence. Nothing automatically reaches `main` or a remote.

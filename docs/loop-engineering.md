# Career CoDesk automatic engineering loop

## What this is

The scaffold is a local-first implementation profile inspired by `SPEC.md`. It applies the useful
Symphony constraints to this repository now:

```text
versioned PLAN + WORKFLOW
          ↓
pin committed source inputs
          ↓
private integration worktree
          ↓
Sol/ultra guide (read-only)
          ↓
Terra/high or explicit Luna/high implementer (task worktree)
          ↓
deterministic verification
          ↓
Sol/ultra independent review (read-only)
          ↓
bounded repair loop or needs-human stop
          ↓
engine-owned commit → private codex/loop-integration branch
```

It is not a complete implementation of the language-agnostic Symphony service. It does not poll a
remote issue tracker, reuse app-server threads, expose an HTTP dashboard, run concurrent tasks,
publish branches, or mutate tickets. The local YAML plan is the tracker Adapter; `codex exec` is the
agent Adapter; JSON state and JSONL events are the operator surface.

## Model policy

The installed Codex catalog on 19 July 2026 advertises all three configured models:

| Role | Profile | Access | Selection |
|---|---|---|---|
| high-level guide | `gpt-5.6-sol`, `ultra` | read-only | required |
| normal designer/implementer | `gpt-5.6-terra`, `high` | task-worktree write | default |
| low-risk fast implementer | `gpt-5.6-luna`, `high` | task-worktree write | task must explicitly opt in |
| independent reviewer | `gpt-5.6-sol`, `ultra` | read-only | required |
| verifier | shell commands from committed policy | task worktree | deterministic |

There is no silent model fallback. A missing model or unsupported reasoning level for a profile
used by the plan makes `doctor` or the run fail visibly; an unavailable configured profile that no
task selects is reported as an optional warning.

## Deep module interface

Normal callers use only these commands:

```bash
python3 -m loop_engine doctor
python3 -m loop_engine status
python3 -m loop_engine once [TASK_ID] [--dry-run]
python3 -m loop_engine run [--max-tasks N]
python3 -m loop_engine approve TASK_ID --approver "role/name" --note "specific approval and conditions"
python3 -m loop_engine reject TASK_ID --approver "role/name" --note "reason the gate is refused"
python3 -m loop_engine retry TASK_ID [--note "answer to the blocked question"]
```

Add global `--json` before the command for machine-readable output. Installing the package in a
virtual environment also provides the `career-loop` command.

Engine outcomes use exit `0` for success, `10` for a human/blocked stop, `20` for an operator or
coordination conflict, `30` for path-policy or Git safety refusal, `40` for an agent failure, `50`
for verification/review failure, and `70` for invalid configuration/plan, corrupt state, or an
unexpected internal failure. Argparse usage errors (such as a missing required flag) retain the
standard plain-text help and exit `2`, even when `--json` is present.

The engine keeps guide, implementation, verification, review, repair, Git, and evidence details
behind this command seam. The Codex process has a real Adapter and can be replaced by a scripted
fake in tests. Filesystem and Git behavior are tested with real temporary repositories rather than
exposed as shallow public ports.

## First-time setup

1. Run the scaffold tests:

   ```bash
   python3 -m unittest discover -s tests -v
   ```

2. Review the new policy and plan. In particular, confirm that `PLAN.yaml` expresses the intended
   prototype and that the first human gate is in the right place.

3. Commit the exact run inputs. Do not use a broad add command in the current dirty worktree. Stage
   only files you intend to make authoritative, including the previously untracked `SPEC.md`:

   ```bash
   git add .gitignore pyproject.toml loop_engine tests WORKFLOW.md PLAN.yaml \
     docs/loop-engineering.md README.md SPEC.md
   git commit -m "build: add isolated engineering loop"
   ```

   The repository currently contains a tracked deletion of the preserved source
   `英国学院职业发展痛点.md` plus untracked PDFs. The scaffold neither stages nor restores those
   changes. Because that source is now part of the pinned policy basis, review and resolve its
   deletion before running the loop—normally restore it, or deliberately remove it from the policy
   basis in a separately reviewed change. The PDFs remain outside the loop policy unless you choose
   to add them.

4. Check the committed source basis and live model catalog:

   ```bash
   python3 -m loop_engine doctor
   python3 -m loop_engine once --dry-run
   ```

The engine refuses execution when `WORKFLOW.md`, `PLAN.yaml`, any configured policy input, or a
task source is absent from the pinned base commit. It also refuses uncommitted changes to those
inputs. This prevents a worktree agent from receiving a different specification than the operator
reviewed.

## Running the plan

Start one task and inspect it before enabling the longer loop:

```bash
python3 -m loop_engine once D001-implementation-rfc
python3 -m loop_engine status
git diff main...codex/loop-integration
```

The first task writes a candidate RFC into the private integration branch. The next run stops at
`G001-approve-rfc` and prints the integration worktree path, normally:

```text
.loop/worktrees/integration
```

Review and, if necessary, edit the RFC there. Change its status to `Approved for prototype
implementation` only when the product authority described by the gate is real. Then approve the
gate from the repository root:

```bash
python3 -m loop_engine approve G001-approve-rfc \
  --approver "<role/name>" \
  --note "Approved by <role/name> for synthetic prototype implementation, subject to <conditions>."
```

The approval command requires an explicit approver identity, runs the gate's deterministic checks,
and records an engine-owned exact-tree Git commit on `codex/loop-integration`. The identity is an
operator attestation recorded for audit; this local harness does not authenticate it or establish
that the person has organisational authority. Confirm that authority outside the harness. Approval
does not merge to `main`, and a commit-message trailer is not treated as approval evidence.

If the evidence or authority is insufficient, refuse the gate instead of fabricating approval:

```bash
python3 -m loop_engine reject G001-approve-rfc \
  --approver "<role/name>" \
  --note "Rejected because <specific evidence, authority, or safety gap>."
```

Rejection is bound to the same gate request and integration base, records a durable decision, and
stops the dependency chain without creating an acceptance commit. A later attempt requires an
explicit `retry --note` describing what changed, then a newly issued gate request.

Continue one task at a time:

```bash
python3 -m loop_engine once
```

Or continue until completion, a human gate, a model/infrastructure error, reviewer rejection, or
repair-budget exhaustion:

```bash
python3 -m loop_engine run
```

## Isolation and evidence

Runtime files are ignored under `.loop/`:

```text
.loop/
  state.json                 authoritative local run and acceptance metadata
  state.json.lock            single-orchestrator lock
  events.jsonl               structured cross-run events
  runs/<run-id>/             prompts, model events, stderr, checks, reviews
  worktrees/integration/     private integration branch
  worktrees/tasks/<task>/    preserved isolated task branches
```

Every agent runs with its task worktree as `cwd`. The engine rejects path escape, agent-created
commits, branch switches, changes outside the task's `allowed_paths`, and changes to workflow/policy
files. It stages each candidate tree, binds verification and review to the resulting Git tree
digest, reruns all checks after every semantic repair, and commits only after a read-only Sol
reviewer accepts that exact tree. The engine creates the accepted commit directly from the reviewed
tree using Git plumbing with repository hooks bypassed, so a hook cannot change the tree between
review and commit.

Acceptance is reconciled only when the persisted task digest, workflow digest, base commit,
reviewed-tree digest, and engine commit agree with Git history. Commit messages and trailers do not
reconstruct acceptance. Preserve `.loop/state.json` and the associated run evidence: deleting that
state loses the acceptance ledger and is not automatically rebuildable from the integration branch.

The engine's own Git writes fast-forward accepted task commits only into
`codex/loop-integration`; it treats detected root-checkout, `main`, ref, remote, or repository-policy
mutation by a child process as a safety failure. This detection is not an OS boundary and does not
promise automatic rollback of a malicious host-side command. Worktrees and evidence are preserved
for inspection. Merge, push, pull request, deployment, tracker writes, and cleanup remain explicit
human actions.

## Recovery and attention states

- An interrupted run keeps its task worktree, run ID, guide output, logs, and state. Before
  continuing, the engine reconciles recorded child PIDs and terminates a stale Codex or verifier
  process group rather than assuming it survived safely.
- `needs_human` records the guide/reviewer questions and stops the loop.
- Retrying a task blocked on a guide or reviewer question requires an explicit answer, for example
  `python3 -m loop_engine retry TASK_ID --note "<decision and authority>"`. The answer is preserved
  for the next run; retry is not an approval shortcut.
- `failed` preserves all evidence. Infrastructure retries are deliberate operator actions: fix the
  cause, run `python3 -m loop_engine retry TASK_ID`, and then run `once` again. They are not consumed
  automatically as semantic repair cycles.
- A task commit created just before a crash can be reconciled only from matching persisted
  task/workflow/base/tree/commit metadata. A trailer by itself cannot resume or accept a task, and
  deleting `.loop/state.json` is not recoverable from trailers.
- The configured limit of three applies to semantic repair cycles triggered by deterministic
  verification or reviewer findings. Deterministic verification failure cannot be overridden by a
  reviewer; explicit infrastructure retries remain manual.

## Trust posture

This is an unattended local coding harness. Committed task descriptions and verification commands
are executable policy and must be code-reviewed. The implementation strips configured tracker and
integration secrets from agent and verification child environments, uses `workspace-write` rather
than danger-full-access for implementers, gives guide/reviewer read-only access, and treats any
request for missing product authority as a stop.

Verifier commands run directly on the host in a non-login shell. Their environment has configured
and commonly named secrets stripped, and their process group is tracked for timeout and stale-PID
cleanup, but this is not a strong OS or network sandbox. Candidate code can still exercise the host
permissions and network access available to that process.

Do not feed the loop untrusted tickets, real learner data, credentials, or externally supplied
shell commands. Run it inside a disposable container or host with independently enforced filesystem
and network controls whenever candidate code is not fully trusted, and before treating it as a
production autonomous-agent service.

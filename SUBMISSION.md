# Career CoDesk submission pack

Deadline: Tuesday, 21 July 2026 at 5:00 PM Pacific time. That is Wednesday, 22 July at 1:00 AM British Summer Time. Aim to submit by 2:00 PM Pacific time, or 10:00 PM British Summer Time, to keep the recommended three-hour buffer.

## Devpost copy

### Project name

Career CoDesk

### Tagline

A local decision workspace that turns synthetic learner needs into capacity-feasible, adviser-approved support plans.

### Short description

Further education careers teams often have learner requests, limited adviser capacity, and several disconnected tools, but no clear way to turn those inputs into a reviewable weekly plan. Career CoDesk is a synthetic demonstrator for that decision point.

It imports fictional learner needs, keeps the original source separate from provisional AI interpretation, and uses deterministic code to test capacity and feasible alternatives. An adviser must approve, amend, or reject every proposal. Only an approved decision can create a weekly plan and a local mock export. Learner feedback can reopen the case without overwriting its history.

The project also includes the engineering system used to build it. A Symphony-inspired loop gave GPT-5.6 Sol the read-only guide and reviewer roles, used GPT-5.6 Terra for implementation, and reserved GPT-5.6 Luna for explicitly selected low-risk work. Codex ran each task in an isolated local worktree, checked deterministic acceptance commands, and stopped at human approval gates. This kept the model focused on a small product slice while preserving an inspectable record of decisions and validation.

Everything runs locally with synthetic data, SQLite, and a deterministic fake AI adapter. There is no live MIS connection, external writeback, real learner data, or production safety claim.

### What it does

- Imports allowlisted synthetic learner needs with source provenance
- Separates provisional AI interpretation from source-qualified facts
- Calculates capacity, alternatives, waiting time, and unmet demand deterministically
- Requires adviser approval before activating a support plan
- Creates an inspectable weekly plan and idempotent local mock export
- Records learner feedback and reopens unresolved cases without rewriting history
- Routes safety-like text out of the ordinary workflow before classification
- Replays eight deterministic evaluation scenarios without runtime network access

### How it was built

The product is a server-rendered Django modular monolith with SQLite. Its modules cover intake and provenance, casework, the AI gateway, planning, decisions, delivery and feedback, export, and audit. The interface is designed around a two-column evidence review so an adviser can compare source statements with provisional interpretation before deciding.

The build workflow is part of the repository. `PLAN.yaml` defines small tasks and human gates. `WORKFLOW.md` assigns GPT-5.6 Sol to guidance and review and GPT-5.6 Terra or Luna to bounded implementation work. The local loop creates isolated branches and worktrees, limits repair cycles, verifies exact candidate trees, and records acceptance evidence before integrating a task.

### Challenges

The hardest part was deciding what AI should not control. Capacity arithmetic, policy checks, scheduling, approval, and activation remain deterministic or human-owned. AI output is provisional, versioned, linked to exact source records, and unable to create a consequential plan on its own.

The second challenge was keeping the automated development loop useful without letting review expand forever. We narrowed review to acceptance criteria, batched fixes into one concentrated repair cycle, used compact evidence summaries, and left nonblocking hardening work for later.

### What is next

The next step is not to connect real college data. It is to test the workflow with careers staff using synthetic scenarios, validate whether the review screen reduces preparation and coordination effort, and define the institutional policy and human process for any future restricted handoff. Live identity, privacy, security, accessibility, MIS integration, and pilot governance would each require separate approval and evidence.

## Three-minute demo script

Keep the finished video under three minutes. Record at 1080p if practical, enlarge the browser text enough to read, hide notifications, and use the populated evaluation database described in the root README.

### 0:00 to 0:20, the problem

"Career CoDesk helps further education careers teams turn learner needs into a weekly support plan they can actually deliver. The problem is not a lack of career information. It is making a transparent decision when demand, adviser time, and available interventions do not line up."

Show the project title and the decision queue.

### 0:20 to 0:50, the boundary and evidence

"This is a local synthetic demonstrator. Every record is fictional, there is no MIS connection, and nothing is sent outside the app. On this case, the adviser can see the original learner statement on the left and the provisional AI interpretation on the right. Unknowns stay visible instead of being turned into facts."

Open an ordinary case. Point to the synthetic-data banner, source evidence, AI label, and unknowns.

### 0:50 to 1:20, deterministic planning

"GPT output does not decide entitlement, capacity, or scheduling. Deterministic planning records the policy version, remaining capacity, waiting time, feasible alternatives, and unmet demand. If there is no capacity, the need remains visible."

Point to the capacity band, rationale, alternatives, and unmet-demand state.

### 1:20 to 1:50, human decision

"The adviser must approve, amend, or reject the proposal and give a reason. The confirmation screen shows the exact evidence being reviewed. Only an approved decision can activate an allocation or create a weekly plan."

Demonstrate the decision controls and confirmation screen. Use a prepared approved case if recording the full transition would take too long.

### 1:50 to 2:20, plan, export, and feedback

"The approved plan keeps its source, decision, owner, timing, effort, and deadline together. Export is only a local mock outbox record with an idempotency key. The learner view shows one approved action and can record that it helped, remains unresolved, needs human help, or needs a source correction. Unresolved feedback reopens the case without deleting its history."

Show the plan detail, local export state, learner action, and a prepared feedback result.

### 2:20 to 2:50, Codex and GPT-5.6

"I built the project with Codex and GPT-5.6 through the engineering loop included in this repository. GPT-5.6 Sol acted as the high-level guide and independent reviewer. GPT-5.6 Terra handled the main design and implementation work, while Luna was available for explicitly selected low-risk tasks. Each task ran in an isolated worktree, deterministic tests decided whether it passed, and human gates approved the product direction and final demonstrator. No API integration or API credits were required."

Briefly show `PLAN.yaml`, `WORKFLOW.md`, the loop status output, and the test result.

### 2:50 to 3:00, close

"Career CoDesk is a small testable answer to one question: can a careers team make a better capacity-aware decision without giving AI decision authority? The next step is a staff walkthrough with synthetic scenarios."

Return to the adviser review screen.

## Recording runbook

```sh
bash product/scripts/run-demo-evaluation.sh
CAREER_CODESK_EVALUATION_SQLITE_PATH="$PWD/product/evaluation-output/evaluation-v1.sqlite3" \
  uv run --project product --locked --no-sync python product/manage.py runserver 127.0.0.1:8000
```

Before recording:

- Open the queue, one ordinary review, one approved plan, the learner view, and `WORKFLOW.md` in separate tabs.
- Check microphone level and record a ten-second sample.
- Keep the voiceover continuous. Cut loading, typing, and navigation mistakes.
- Watch the exported video once with headphones and once with sound low.
- Confirm the video says both "Codex" and "GPT-5.6" and explains their different roles.
- Upload to YouTube as public or unlisted, wait for processing, then test the link in a private browser window.

## Final submission checklist

- [ ] Run the product from a fresh local database and complete the main flow.
- [ ] Run the verification and eight-scenario evaluation commands in the root README.
- [ ] Record and upload a public or unlisted YouTube video under three minutes.
- [ ] Paste the public video link into Devpost.
- [ ] Run `/feedback` in the official Codex interface used for most of the work and paste the Session ID into Devpost.
- [ ] Publish the final local submission branch to the code repository.
- [ ] If the repository stays private, grant access to `testing@devpost.com` and `build-week-event@openai.com`.
- [ ] Add every team member and confirm that each invitation is accepted.
- [ ] Read the project description aloud and edit any sentence that does not sound like you.
- [ ] Save, submit, then open Devpost My Projects and confirm the project has a green `Submitted` label rather than draft status.
- [ ] Test the repository and video links from a logged-out or private browser session.

## Fields to collect

- YouTube URL: `TODO`
- Codex `/feedback` Session ID: `TODO`
- Final repository URL: `https://github.com/xingaobio/career-codesk`
- Team invitations accepted: `TODO`
- Devpost status checked as `Submitted`: `TODO`

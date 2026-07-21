# Career CoDesk submission pack

Deadline: Tuesday, 21 July 2026 at 5:00 PM Pacific time. That is Wednesday, 22 July at 1:00 AM British Summer Time. Aim to submit by 2:00 PM Pacific time, or 10:00 PM British Summer Time, to keep the recommended three-hour buffer.

## Devpost copy

### Project name

Career CoDesk

### Tagline

A local decision workspace that turns synthetic learner needs into capacity-feasible, adviser-approved support plans.

### Short description

Further education careers teams often have learner requests, limited adviser capacity, and several disconnected tools, but no clear way to turn those inputs into a reviewable weekly plan. Career CoDesk is a synthetic demonstrator for that decision point.

It is an operations workspace for FE careers advisers—not a job board, automated job-matching service, or learner-facing careers bot.

It imports fictional learner needs, keeps the original source separate from provisional AI interpretation, and uses deterministic code to test capacity and feasible alternatives. An adviser must approve, amend, or reject every proposal. Only an approved decision can create a weekly plan and a local mock export. Learner feedback can reopen the case without overwriting its history.

The project also includes the engineering system used to build it. We adapted the orchestration pattern from OpenAI's [open-source Symphony specification](https://openai.com/index/open-source-codex-orchestration-symphony/) into a local loop: GPT-5.6 Sol held the read-only guide and reviewer roles, GPT-5.6 Terra handled implementation, and GPT-5.6 Luna was reserved for explicitly selected low-risk work. Codex ran each agent implementation task in an isolated local worktree, checked deterministic acceptance commands, and stopped at human approval gates. This kept the model focused on a small product slice while preserving an inspectable record of decisions and validation.

The evaluated product runs locally with synthetic data, SQLite, and a deterministic fake AI adapter. The public reviewer site uses fictional composite identities and resets every interaction on refresh. College connectors, external writeback, real learner data, and production safety claims remain outside this prototype.

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

The build workflow is part of the repository and adapts OpenAI Symphony's task-oriented orchestration and isolated-workspace pattern rather than claiming to run the complete Symphony service. `PLAN.yaml` defines small tasks and human gates. `WORKFLOW.md` assigns GPT-5.6 Sol to guidance and review and GPT-5.6 Terra or Luna to bounded implementation work. The local loop creates isolated branches and worktrees, limits repair cycles, verifies exact candidate trees, and records acceptance evidence before integrating a task.

### Challenges

The hardest part was deciding what AI should not control. Capacity arithmetic, policy checks, scheduling, approval, and activation remain deterministic or human-owned. AI output is provisional, versioned, linked to exact source records, and unable to create a consequential plan on its own.

The second challenge was keeping the automated development loop useful without letting review expand forever. We narrowed review to acceptance criteria, batched fixes into one concentrated repair cycle, used compact evidence summaries, and left nonblocking hardening work for later.

### What is next

The next step is not to connect real college data. It is to test the workflow with careers staff using synthetic scenarios, validate whether the review screen reduces preparation and coordination effort, and define the institutional policy and human process for any future restricted handoff. Live identity, privacy, security, accessibility, MIS integration, and pilot governance would each require separate approval and evidence.

## Three-minute demo talk track

Keep the finished video under three minutes. Record at 1080p if practical, enlarge the browser text enough to read, hide notifications, and speak from the screen rather than reading a script. Open the five-slide deck and the interactive reviewer walkthrough in two tabs so you can switch manually; the deck intentionally has no timer or demo-launch buttons.

### 0:00 to 0:20 · Slide 1: the capacity problem

- England's 213 colleges prepare more than 1.6 million learners.
- In Ofsted's 2024 research sample, all 25 colleges and 7 local authorities reported difficulty recruiting Level 6 careers advisers.
- Say explicitly that these are separate capacity signals, not a claimed national learner-to-adviser ratio.

### 0:20 to 0:40 · Slide 2: what Career CoDesk does

- Say who it is for first: Career CoDesk is a weekly decision workspace for FE careers advisers.
- Follow the four steps: learner need, evidence plus capacity, adviser decision, then support and feedback.
- State the boundary clearly: it is not a job board, automated job-matching service, or learner-facing careers bot.

### 0:40 to 1:35 · Reviewer site: one complete case

- Switch to the reviewer walkthrough and speak as a careers adviser choosing Olivia K. or Muhammad R. for weekly support review.
- Click `Evidence review`: point to the fictional source statement, provisional AI interpretation and visible unknown.
- Click `Capacity plan`: point to the available slot, feasible alternative and retained unmet demand.
- Mention that machine identifiers are hidden in the presentation story but technical evidence remains inspectable.
- Click `Human decision`, then `Amend route` to show that an amendment requires replanning and a second confirmation.
- Click `Learner feedback`, then `I am still unsure` to show that feedback reopens review without deleting history.
- State the boundary once: all visible identities are fictional composites and the controls reset on refresh.

### 1:35 to 1:55 · Slide 3: human in the loop

- The gateway is designed for an OpenAI API adapter that can organise evidence and suggest education support; it never activates a plan.
- For a repeatable evaluation, this MVP runs a deterministic local adapter behind that same gateway boundary.
- The careers adviser approves, amends or rejects with a reason; unresolved learner feedback returns the case to the team.

### 1:55 to 2:18 · Slide 4: integration and privacy

- Show the MIS/CRM/CSV → adapter/core → approved-output architecture.
- Name the safeguards: field allowlist, evidence/inference separation, human gate and traceability.
- Do not claim GDPR compliance. Say that DPIA, retention, lawful basis and access control remain institutional responsibilities.

### 2:18 to 2:42 · Slide 5: OpenAI workflow and team

- Name the method first: the engineering workflow adapts OpenAI's open-source Symphony orchestration pattern into isolated Codex implementation runs.
- GPT-5.6 Sol with ultra reasoning guided and independently reviewed.
- GPT-5.6 Terra and Luna handled design, implementation and verification in Codex CLI, with up to 16 subagents.
- Deterministic tests and a human gate—not a model—decided completion.
- Name the team: Xin Gao led product, research and AI workflow; Chelsea Li led marketing, testing and the demo.

### 2:42 to 2:50 · close

End on one sentence: "Career CoDesk tests whether a careers team can make a better capacity-aware decision without giving AI decision authority."

## Recording runbook

Open `docs/video-demo.html` and use Left/Right Arrow or Space to navigate; press `F` for fullscreen. Keep `https://career-codesk-review.vercel.app/` open in the second tab and switch to it manually for the interactive middle section. The public reviewer page opens without an account. For an offline recording fallback, run `python3 -m http.server 8030 --directory showcase/public` and use `http://127.0.0.1:8030/`.

Before recording:

- Put Slide 1 in the first tab and the reviewer walkthrough at `Evidence review` in the second.
- Close unrelated tabs, hide notifications and zoom until every label is readable.
- Check microphone level and record a ten-second sample.
- Keep the voiceover continuous. Cut loading, typing and navigation mistakes.
- Watch the exported video once with headphones and once with sound low.
- Confirm the video says both "Codex" and "GPT-5.6" and explains their different roles.
- Upload to YouTube as public or unlisted, wait for processing, then test the link in a private browser window.

## Final submission checklist

- [ ] Run the product from a fresh local database and complete the main flow.
- [ ] Run the verification and eight-scenario evaluation commands in the root README.
- [ ] Record and upload a public or unlisted YouTube video under three minutes.
- [ ] Paste the public video link into Devpost.
- [x] Save the relevant Codex Session IDs and identify the primary implementation session outside the public repository.
- [ ] Paste the primary `/feedback` Session ID into Devpost.
- [ ] Publish the final local submission branch to the code repository.
- [ ] If the repository stays private, grant access to `testing@devpost.com` and `build-week-event@openai.com`.
- [ ] Add every team member and confirm that each invitation is accepted.
- [ ] Read the project description aloud and edit any sentence that does not sound like you.
- [ ] Save, submit, then open Devpost My Projects and confirm the project has a green `Submitted` label rather than draft status.
- [x] Test the public reviewer link without a login and confirm the interactive evidence stage loads.
- [ ] Test the repository and final YouTube link from a logged-out or private browser session.

## Fields to collect

- YouTube URL: `TODO`
- Reviewer walkthrough: `https://career-codesk-review.vercel.app/` (public; no login required)
- Primary Codex `/feedback` Session ID: paste the saved implementation-session ID directly into Devpost; do not publish it in the repository.
- Final repository URL: `https://github.com/xingaobio/career-codesk`
- Team invitations accepted: `TODO`
- Devpost status checked as `Submitted`: `TODO`

# Synthetic evaluation demonstrator

## Run

Run from repository root:

```sh
bash product/scripts/run-demo-evaluation.sh
```

It creates `product/evaluation-output/evaluation-v1.sqlite3` and `product/evaluation-output/report-v1.json` for inspection.

## Assumptions

- All fixture aliases and source statements are synthetic, fixed, and attested.
- The fixed adviser identity is a simulation, not production authentication.
- Capacity and schedule feasibility are deterministic demo-policy calculations.
- A successful export attempt means only a local mock-outbox record persisted.

## Non-claims

This is not a live MIS integration, writeback, booking, email, calendar, or provider request. It does not use real learner data, replace Level 6 personal guidance, diagnose anyone, predict NEET status, or establish compliance. The safety scenario is a restricted local handoff marker, not a safety process.

## Expected evidence

`report-v1.json` has eight scenario aliases and stable metrics. The database retains source, gateway, planner, decision, delivery, outcome, and mock-export links.

| Scenario | Expected report fields |
| --- | --- |
| happy-path | `approved_allocations: 1`, `helped_outcomes: 1` |
| over-capacity | `demand: 2`, `allocations: 1`, `unmet_demand: 1` |
| malformed-input | `rejected_rows: 1`, `ordinary_records_created: 0` |
| ai-failure | `disposition: adapter_error`, no hypothesis or consequential record |
| safety-exit | one restricted exit and no ordinary records |
| override | proposed/inactive/proposed/active state changes and separate approval |
| failed-export | failed local attempt followed by succeeded retry |
| reopen | `open>active`, `active>closed`, `closed>open` |

The `checks` section records AI schema/disposition handling, planner constraints and consumption, provenance, approval gates, semantic/contrast smoke checks, denied-socket runtime, and repository fixture hygiene.

## Known gaps

The accessibility check is a deterministic template/CSS smoke check, not a WCAG audit. The socket guard covers evaluator runtime, not dependency installation. The hygiene scan is not a complete security or privacy audit. SQLite is a disposable local demo store.

## Cleanup and reset

To reset exactly the generated evaluator evidence, run:

```sh
rm -f product/evaluation-output/evaluation-v1.sqlite3 product/evaluation-output/report-v1.json
```

Do not delete individual rows from the evaluation database: evidence is append-only. Rerunning the command performs this limited reset.

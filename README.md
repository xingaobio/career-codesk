# Career CoDesk

Career CoDesk is an early-stage concept for an AI-assisted career-guidance operations platform for UK further-education providers.

The working product thesis is:

> Career CoDesk converts learner-needs data into a capacity-feasible, adviser-approved intervention plan and records the approved decision in the college's existing system.

## Current baseline

- Version: `0.1.0-early`
- Status: Product exploration; not an approved implementation specification
- Baseline document: [docs/versions/v0.1.0-early-product-concept.md](docs/versions/v0.1.0-early-product-concept.md)
- Versioning policy: [docs/versions/README.md](docs/versions/README.md)
- Change history: [CHANGELOG.md](CHANGELOG.md)

## Automatic engineering loop

This repository now includes a local, Symphony-inspired implementation-run scaffold. It turns the
machine-readable [PLAN.yaml](PLAN.yaml) into isolated guide → implement → verify → review → repair
runs whose engine-owned integration targets only a private local branch, never `main` or a remote.

- Repository policy and model routing: [WORKFLOW.md](WORKFLOW.md)
- Operator guide and safety model: [docs/loop-engineering.md](docs/loop-engineering.md)
- Run-engine implementation: [loop_engine](loop_engine)

The current plan begins by drafting a new implementation RFC and then stops at a human approval
gate. Product code cannot become dependency-ready while the `0.1.0-early` exploration snapshot is
the only authority.

Quick structural check:

```bash
python3 -m loop_engine doctor --no-model-check
```

The doctor intentionally reports that execution is not ready while `SPEC.md`, `WORKFLOW.md`,
`PLAN.yaml`, or another policy input is uncommitted. See the operator guide before starting a run.

Accepted work is bound to persisted task, workflow, base-commit, reviewed-tree, and engine-commit
metadata; commit-message trailers are not an acceptance or recovery mechanism. Runtime state under
`.loop/` is therefore evidence that should be preserved, not a cache that can be rebuilt after
deletion. Verification commands execute on the host and should be run in a disposable container
when task code is not fully trusted.

Human gates support explicit approve and reject decisions. The recorded `--approver` value is an
operator attestation for audit, not authenticated proof of organisational authority.

## Original project materials

- [product_definition.md](product_definition.md)
- [Adoption Rates of Triage and Digital Tracking Systems in UK FE Colleges.md](Adoption%20Rates%20of%20Triage%20and%20Digital%20Tracking%20Systems%20in%20UK%20FE%20Colleges.md)
- [英国学院职业发展痛点.md](英国学院职业发展痛点.md)

These source documents are preserved as originally provided. Later snapshots should reference them rather than silently rewriting their history.

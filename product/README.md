# Career CoDesk product foundation

This is a local, server-rendered Django foundation for the approved synthetic prototype. It uses
SQLite, a deterministic fake AI seam, an in-process mock outbox, and no external services or
credentials. It is deliberately not a production deployment or authentication system.

## Local commands

Requires Python 3.9 and `uv`. From the repository root:

```sh
uv sync --project product --all-groups --locked
uv run --project product --locked --no-sync python product/manage.py migrate
uv run --project product --locked --no-sync python product/manage.py runserver 127.0.0.1:8000
```

Open `http://127.0.0.1:8000/`. The server is documented and configured for loopback-only use.
Run tests with:

```sh
(cd product && uv run --locked --no-sync python manage.py test tests)
bash scripts/verify-product.sh
```

## Prototype boundaries

Every source must be labelled `Synthetic mock source — no MIS connection.` Fixtures are versioned,
deterministic, and synthetic-only; see `fixtures/foundation-manifest.json`. This repository contains
no learner records at foundation stage. Do not add real, pseudonymised, mapped, SEND, medical,
safeguarding, or welfare data.

Local identity is a fixed manager/adviser simulation, not production authentication: there are no
passwords, SSO, institutional permissions, or access-control claims. The app does not connect to an
MIS, email, calendar, provider, payment service, or any external system; mock exports remain local.
It does not replace Level 6 personal guidance, diagnose learners, predict NEET status, or claim
Gatsby, Ofsted, statutory, or legal compliance. Safety-like signals are reserved for restricted
human handling and never become an ordinary-workflow score.

SQLite is appropriate for this deterministic local demonstration. A later, separately approved
implementation may migrate the shared relational store to PostgreSQL; that is not implemented here.

## Module boundaries

`career_codesk/modules/` contains small published contracts for intake/provenance, casework, AI,
planning, decisions, delivery/feedback, export, and audit/evaluation. `composition.py` is the only
wiring point. The canonical domain records are persisted in the shared SQLite store with stable
non-sequential IDs: source captures and corrections, provisional hypotheses, adviser decisions,
allocation proposals, delivery/outcome evidence, local mock writeback attempts, and restricted
safety exits. Source evidence, AI hypotheses, and adviser decisions are append-only. Case state is
a current projection backed by immutable transitions; only the simulated adviser may manually move
it. Safety exits use a restricted repository path, have no score, and prevent ordinary processing.

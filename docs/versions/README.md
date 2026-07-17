# Product snapshot versioning

The `docs/versions` directory preserves the project's product reasoning at meaningful decision points.

## Version format

Use semantic-style versions:

- `0.x`: discovery, validation, and pre-product-definition work.
- `1.0`: first product definition approved for implementation.
- Patch version: clarification that does not change the product boundary.
- Minor version: a meaningful workflow, market-positioning, or architecture change.
- Major version: a change to the product's core customer, problem, or system boundary.

Labels such as `early`, `draft`, or `validated` describe maturity and are not substitutes for a version number.

## Rules

1. Do not overwrite an earlier snapshot when the product direction changes.
2. Add a new snapshot and record the change in `CHANGELOG.md`.
3. Separate observed evidence, assumptions, decisions, and open questions.
4. Date market and regulatory claims because they can become stale.
5. Link decisions back to the source material or research that motivated them.
6. Treat a snapshot as approved only when its status explicitly says so.

## Suggested Git practice

- Commit each meaningful product decision separately.
- Use messages such as `docs: capture v0.2 product boundary`.
- Tag approved baselines, for example `v0.2.0` or `v1.0.0`.
- Use branches for implementation experiments; keep product snapshots on the main project history.

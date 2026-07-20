# Synthetic fixtures

`foundation-manifest.json` is the versioned convention for every future demo fixture. It fixes the
UTC clock, seed, fixture/schema versions, and demo actor IDs. Its `synthetic_data_attestation` must
remain `true`; fixtures must contain only obviously synthetic data and must label every source:
`Synthetic mock source — no MIS connection.`

The intake files contain only obviously synthetic learner fixtures. Never add real, pseudonymised,
mapped, SEND, medical, safeguarding, or welfare data. Fixtures are local inputs only: there is no
MIS connection, external write, or live integration.

`intake/schema-v1.md` documents the only learner-check-in CSV contract. Each scenario CSV has a
same-named `*-manifest.json` with fixed clock, seed, versions, source label, and attestation. Direct
identifiers, disallowed sensitive values, and unexpected headers are rejected without retaining
their values. Safety-like fixture text is routed only to the restricted human-handling exit.

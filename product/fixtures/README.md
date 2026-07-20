# Synthetic fixtures

`foundation-manifest.json` is the versioned convention for every future demo fixture. It fixes the
UTC clock, seed, fixture/schema versions, and demo actor IDs. Its `synthetic_data_attestation` must
remain `true`; fixtures must contain only obviously synthetic data and must label every source:
`Synthetic mock source — no MIS connection.`

This foundation intentionally contains no learner records. Never add real, pseudonymised, mapped,
SEND, medical, safeguarding, or welfare data. Fixtures are local inputs only: there is no MIS
connection, external write, or live integration.

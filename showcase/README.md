# Career CoDesk reviewer showcase

This standalone site presents the implemented Career CoDesk workflow with readable, fictional composite learner identities. It is a presentation facade, not a second product backend: every interaction is client-side, resets on refresh, and leaves the Django product database and evaluation evidence untouched.

Public reviewer URL: <https://career-codesk-review.vercel.app/>

## Local preview

```sh
npm run dev
```

Open `http://127.0.0.1:8030/`.

## Validate and build

```sh
npm test
```

The build requires only the installed Node.js runtime and creates a dependency-free Cloudflare Worker bundle under `dist/` for Sites hosting.

## Public-demo boundary

- All names are fictional composites with abbreviated surnames.
- No real learner names, contact details, dates of birth, addresses or institutional records are used.
- Machine identifiers are hidden from the public narrative and represented by stable `SIM-###` display references.
- The MIS adapter is an interface boundary; no partner connector is enabled in this showcase.
- Privacy architecture is a design claim, not a GDPR-compliance claim. Production DPIA, retention, lawful basis, access control and connector acceptance remain institutional responsibilities.

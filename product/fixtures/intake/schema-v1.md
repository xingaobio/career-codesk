# Synthetic check-in CSV schema v1

This local-only import accepts UTF-8 CSV files with exactly these four required columns, in any
order: `synthetic_identifier`, `course_code`, `cohort_code`, and `need_statement`.

`synthetic_identifier` must start with `synthetic-` and is bounded to 128 characters.
`course_code` and `cohort_code` are each bounded to 64 characters, and `need_statement` is bounded
to 2,000 characters. Learner rows contain no version, clock, seed,
source, or attestation metadata.

An accompanying manifest supplies `schema_version` (`intake-csv-v1`), `fixture_version`,
`source_version`, `clock_utc`, `seed`, `source_label`, and a literal
`synthetic_data_attestation: true`. The source label is always `Synthetic mock source — no MIS
connection.` `fixture_version` and `source_version` are non-empty strings of at most 64 characters;
`clock_utc` is a UTC timestamp in `YYYY-MM-DDTHH:MM:SSZ` format; and `seed` is an integer from 0 to
2,147,483,647. Exact replay of the same manifest and bytes returns the stored outcome, including a
rejected manifest. Reusing a valid source label and source version with different bytes or manifest
metadata is a non-mutating conflict. Intake stores only one-way payload and manifest digests for
rejected manifests, never their raw values.

Headers and values for direct identifiers or disallowed sensitive material are rejected. The
bounded prototype value gate recognises email addresses; UK mobile numbers in compact, spaced,
hyphenated, dotted, and `+44` forms; labelled names; labelled dates of birth; and labelled street
addresses. It also rejects the bounded sensitive terms `diagnosis`, `diagnosed`, `medical`,
`medication`, `SEND`, `safeguarding`, and `welfare`. This is not comprehensive PII detection.
Raw rejected values are never retained in import evidence, summaries, or normal logs. The only
quarantine outcome is the deterministic prototype safety-like text gate; it creates restricted
human-handling evidence and is not a safeguarding assessment, score, or ordinary AI input.
Safety-like content takes this restricted route even when it includes a disallowed sensitive term,
but never when it overlaps a detected direct identifier.

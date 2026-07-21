import json
import logging
from pathlib import Path

from django.test import TestCase

from career_codesk.modules.ai_gateway.models import NeedHypothesis
from career_codesk.modules.casework.models import Case
from career_codesk.modules.decisions.models import SupportDecision
from career_codesk.modules.delivery_feedback.models import DeliveryEvent
from career_codesk.modules.export.models import WritebackAttempt
from career_codesk.modules.intake_provenance.models import (
    Enrolment,
    ImportBatch,
    ImportRowResult,
    Learner,
    NeedCapture,
    SafetyExit,
)
from career_codesk.modules.intake_provenance.services import (
    OrdinaryCaptureRepository,
    SyntheticCsvIntakeService,
)
from career_codesk.modules.planning.models import InterventionAllocation


class SyntheticIntakeTests(TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1] / "fixtures" / "intake"
        self.service = SyntheticCsvIntakeService()
        self.manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))

    def import_fixture(self, name, source_version):
        manifest = {**self.manifest, "source_version": source_version}
        return self.service.import_csv((self.root / name).read_bytes(), manifest)

    def test_valid_import_preserves_source_qualified_evidence_and_exact_replay(self):
        first = self.import_fixture("valid.csv", "valid-v1")
        second = self.import_fixture("valid.csv", "valid-v1")
        self.assertEqual((first.accepted, first.rejected, first.quarantined), (1, 0, 0))
        self.assertTrue(second.replayed)
        self.assertEqual(
            (Learner.objects.count(), Enrolment.objects.count(), NeedCapture.objects.count()),
            (1, 1, 1),
        )
        capture = NeedCapture.objects.get()
        self.assertEqual(capture.import_batch_id, first.batch_id)
        self.assertEqual(capture.enrolment.import_batch_id, first.batch_id)
        self.assertEqual(capture.source_version, "valid-v1")
        self.assertEqual(ImportRowResult.objects.get().error_codes, [])

    def test_malformed_and_unattested_input_create_no_domain_records(self):
        malformed = self.import_fixture("malformed.csv", "malformed-v1")
        unattested_manifest = {
            **self.manifest,
            "source_version": "unattested-v1",
            "synthetic_data_attestation": False,
        }
        unattested = self.service.import_csv(
            (self.root / "valid.csv").read_bytes(), unattested_manifest
        )
        self.assertEqual(
            [(row.row_number, row.status, row.error_codes, row.fields) for row in malformed.rows],
            [(0, "rejected", ("csv_malformed",), ())],
        )
        self.assertEqual(unattested.rows[0].error_codes, ("synthetic_attestation_required",))
        self.assertEqual(
            (
                Learner.objects.count(),
                Enrolment.objects.count(),
                Case.objects.count(),
                NeedCapture.objects.count(),
            ),
            (0, 0, 0, 0),
        )
        self.assertEqual(ImportBatch.objects.count(), 2)

    def test_duplicate_later_row_is_rejected_without_partial_records(self):
        summary = self.import_fixture("duplicate.csv", "duplicate-v1")
        self.assertEqual(
            [(row.row_number, row.status, row.error_codes) for row in summary.rows],
            [(2, "accepted", ()), (3, "rejected", ("duplicate_row",))],
        )
        self.assertEqual(
            (Learner.objects.count(), Enrolment.objects.count(), NeedCapture.objects.count()),
            (1, 1, 1),
        )

    def test_disallowed_headers_and_sensitive_values_are_redacted(self):
        sentinel = "not-permitted@example.invalid"
        with self.assertLogs(
            "career_codesk.modules.intake_provenance.services", logging.INFO
        ) as logs:
            summary = self.import_fixture("disallowed.csv", "disallowed-v1")
        self.assertEqual(summary.rows[0].error_codes, ("forbidden_header",))
        self.assertNotIn(sentinel, str(summary))
        self.assertNotIn(sentinel, "\n".join(logs.output))
        self.assertNotIn(sentinel, str(ImportBatch.objects.values()))
        self.assertEqual((Learner.objects.count(), NeedCapture.objects.count()), (0, 0))

    def test_sensitive_value_in_an_allowlisted_column_is_redacted_and_rejected(self):
        sentinel = "hidden-person@example.invalid"
        csv_bytes = (
            b"synthetic_identifier,course_code,cohort_code,need_statement\n"
            b"synthetic-learner-sensitive,SYN-ROUTES-01,SYN-2026-A,"
            b"Contact " + sentinel.encode("ascii") + b"\n"
        )
        with self.assertLogs(
            "career_codesk.modules.intake_provenance.services", logging.INFO
        ) as logs:
            summary = self.service.import_csv(
                csv_bytes, {**self.manifest, "source_version": "sensitive-value-v1"}
            )
        self.assertEqual(summary.rows[0].error_codes, ("sensitive_value_detected",))
        self.assertNotIn(sentinel, str(summary))
        self.assertNotIn(sentinel, "\n".join(logs.output))
        self.assertEqual((Learner.objects.count(), NeedCapture.objects.count()), (0, 0))

    def test_representative_direct_identifiers_are_redacted_and_rejected(self):
        examples = (
            ("My name: Sentinel Person", "Sentinel Person"),
            ("Date of birth: 01/02/2007", "01/02/2007"),
            ("Address: 12 Sentinel Street", "12 Sentinel Street"),
            ("Call me on 07123 456 789", "07123 456 789"),
        )
        for index, (statement, sentinel) in enumerate(examples):
            with (
                self.subTest(statement=statement),
                self.assertLogs(
                    "career_codesk.modules.intake_provenance.services", logging.INFO
                ) as logs,
            ):
                summary = self.service.import_csv(
                    (
                        "synthetic_identifier,course_code,cohort_code,need_statement\n"
                        f"synthetic-direct-{index},SYN-ROUTES-01,SYN-2026-A,{statement}\n"
                    ).encode(),
                    {**self.manifest, "source_version": f"direct-identifier-{index}-v1"},
                )
            self.assertEqual(summary.rows[0].error_codes, ("sensitive_value_detected",))
            self.assertNotIn(sentinel, str(summary))
            self.assertNotIn(sentinel, "\n".join(logs.output))
            self.assertNotIn(sentinel, str(ImportBatch.objects.values()))
        self.assertEqual((Learner.objects.count(), NeedCapture.objects.count()), (0, 0))

    def test_rejected_manifest_values_are_redacted_from_import_evidence(self):
        sentinel = "not-permitted@example.invalid"
        summary = self.service.import_csv(
            (self.root / "valid.csv").read_bytes(),
            {**self.manifest, "source_version": sentinel},
        )
        self.assertEqual(summary.rows[0].error_codes, ("manifest_value_invalid",))
        batch = ImportBatch.objects.get()
        self.assertEqual(batch.source_label, "Rejected manifest — redacted")
        self.assertNotIn(sentinel, str(batch.__dict__))

    def test_rejected_manifest_exact_replay_is_redacted_and_non_mutating(self):
        sentinel = "not-permitted@example.invalid"
        rejected_manifest = {**self.manifest, "source_version": sentinel}
        csv_bytes = (self.root / "valid.csv").read_bytes()

        first = self.service.import_csv(csv_bytes, rejected_manifest)
        second = self.service.import_csv(csv_bytes, rejected_manifest)

        self.assertEqual(first.rows[0].error_codes, ("manifest_value_invalid",))
        self.assertTrue(second.replayed)
        self.assertEqual(ImportBatch.objects.count(), 1)
        self.assertNotIn(sentinel, str(ImportBatch.objects.values()))
        self.assertNotIn(sentinel, str(ImportRowResult.objects.values()))

    def test_distinct_rejected_manifests_have_distinct_redacted_identities(self):
        csv_bytes = (self.root / "valid.csv").read_bytes()
        first = self.service.import_csv(
            csv_bytes, {**self.manifest, "source_version": "one@example.invalid"}
        )
        second = self.service.import_csv(
            csv_bytes, {**self.manifest, "source_version": "two@example.invalid"}
        )

        self.assertFalse(first.replayed)
        self.assertFalse(second.replayed)
        self.assertEqual(ImportBatch.objects.count(), 2)
        self.assertEqual(
            {batch.source_label for batch in ImportBatch.objects.all()},
            {"Rejected manifest — redacted"},
        )
        self.assertEqual(len({batch.manifest_digest for batch in ImportBatch.objects.all()}), 2)

    def test_manifest_types_and_fixed_formats_are_validated_without_raw_persistence(self):
        invalid_manifests = (
            {**self.manifest, "clock_utc": "2026-01-01 00:00:00"},
            {**self.manifest, "clock_utc": "2026-13-01T00:00:00Z"},
            {**self.manifest, "clock_utc": "2026-02-29T00:00:00Z"},
            {**self.manifest, "clock_utc": "2026-01-01T24:00:00Z"},
            {**self.manifest, "clock_utc": "2026-01-01T00:60:00Z"},
            {**self.manifest, "clock_utc": "2026-01-01T00:00:60Z"},
            {**self.manifest, "seed": "20260101"},
            {**self.manifest, "seed": True},
            {**self.manifest, "seed": -1},
        )
        csv_bytes = (self.root / "valid.csv").read_bytes()
        for manifest in invalid_manifests:
            with self.subTest(manifest=manifest):
                summary = self.service.import_csv(csv_bytes, manifest)
                self.assertEqual(summary.rows[0].error_codes, ("manifest_value_invalid",))
        self.assertEqual(ImportBatch.objects.count(), len(invalid_manifests))

    def test_safety_text_is_quarantined_and_is_not_an_ordinary_or_ai_input(self):
        summary = self.import_fixture("safety-exit.csv", "safety-v1")
        self.assertEqual((summary.accepted, summary.rejected, summary.quarantined), (0, 0, 1))
        capture = NeedCapture.objects.get()
        self.assertEqual(SafetyExit.objects.get().source_capture_id, capture.id)
        self.assertEqual(OrdinaryCaptureRepository().for_case(capture.case_id).count(), 0)
        self.assertEqual(NeedHypothesis.objects.count(), 0)
        self.assertEqual(InterventionAllocation.objects.count(), 0)
        self.assertEqual(SupportDecision.objects.count(), 0)
        self.assertEqual(DeliveryEvent.objects.count(), 0)
        self.assertEqual(WritebackAttempt.objects.count(), 0)

    def test_safety_or_safeguarding_text_overrides_sensitive_content_but_not_identifiers(self):
        safety_cases = (
            "I do not feel safe at home and need to talk to someone.",
            "I am thinking of self-harm and take medication.",
        )
        for index, statement in enumerate(safety_cases):
            with self.subTest(statement=statement):
                summary = self.service.import_csv(
                    (
                        "synthetic_identifier,course_code,cohort_code,need_statement\n"
                        f"synthetic-safety-{index},SYN-ROUTES-01,SYN-2026-A,{statement}\n"
                    ).encode(),
                    {**self.manifest, "source_version": f"safety-overlap-{index}-v1"},
                )
                self.assertEqual(
                    (summary.accepted, summary.rejected, summary.quarantined), (0, 0, 1)
                )
                capture = NeedCapture.objects.get(
                    learner__synthetic_identifier=f"synthetic-safety-{index}"
                )
                self.assertEqual(OrdinaryCaptureRepository().for_case(capture.case_id).count(), 0)
        self.assertEqual(SafetyExit.objects.count(), 2)

        direct_identifier = "I am unsafe. My name: Sentinel Person"
        with self.assertLogs(
            "career_codesk.modules.intake_provenance.services", logging.INFO
        ) as logs:
            summary = self.service.import_csv(
                (
                    "synthetic_identifier,course_code,cohort_code,need_statement\n"
                    f"synthetic-safety-direct,SYN-ROUTES-01,SYN-2026-A,{direct_identifier}\n"
                ).encode(),
                {**self.manifest, "source_version": "safety-direct-identifier-v1"},
            )
        self.assertEqual(summary.rows[0].error_codes, ("sensitive_value_detected",))
        self.assertNotIn("Sentinel Person", str(summary))
        self.assertNotIn("Sentinel Person", "\n".join(logs.output))
        self.assertNotIn("Sentinel Person", str(NeedCapture.objects.values()))
        self.assertEqual((Learner.objects.count(), NeedCapture.objects.count()), (2, 2))

    def test_reused_source_version_with_different_bytes_is_non_mutating(self):
        self.import_fixture("valid.csv", "conflict-v1")
        result = self.service.import_csv(
            b"synthetic_identifier,course_code,cohort_code,need_statement\n"
            b"synthetic-learner-other,SYN,SYN,Other\n",
            {**self.manifest, "source_version": "conflict-v1"},
        )
        self.assertTrue(result.source_version_conflict)
        self.assertIsNone(result.batch_id)
        self.assertEqual((ImportBatch.objects.count(), Learner.objects.count()), (1, 1))

    def test_fixture_manifests_are_attested_and_have_distinct_fixed_source_versions(self):
        names = ("valid", "malformed", "duplicate", "disallowed", "safety-exit")
        manifests = [
            json.loads((self.root / f"{name}-manifest.json").read_text(encoding="utf-8"))
            for name in names
        ]
        self.assertEqual(
            {manifest["source_version"] for manifest in manifests},
            {
                "valid-fixture-v1",
                "malformed-fixture-v1",
                "duplicate-fixture-v1",
                "disallowed-fixture-v1",
                "safety-exit-fixture-v1",
            },
        )
        for manifest in manifests:
            self.assertTrue(manifest["synthetic_data_attestation"])
            self.assertEqual(manifest["clock_utc"], "2026-01-01T00:00:00Z")
            self.assertEqual(manifest["seed"], 20260101)

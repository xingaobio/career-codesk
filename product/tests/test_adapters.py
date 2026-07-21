from django.test import SimpleTestCase

from career_codesk.modules.ai_gateway.contracts import (
    AiRequest,
    DeterministicFakeAdapter,
    SourceReference,
)
from career_codesk.modules.export.contracts import LocalMockOutbox


class AdapterTests(SimpleTestCase):
    def test_fake_ai_covers_the_bounded_tasks_without_credentials(self):
        gateway = DeterministicFakeAdapter()
        for task_kind, identity in (
            ("intake_interpretation", "case_id"),
            ("need_hypothesis", "case_id"),
            ("cohort_explanation", "cohort_id"),
            ("adviser_draft", "case_id"),
        ):
            request = AiRequest(
                task_kind=task_kind,
                source_records=(SourceReference("capture-1", "need_capture", "csv-v1"),),
                input_metadata={identity: "case-or-cohort-1", "capture_ids": ["capture-1"]},
                prompt_version="prompt-v1",
                output_schema_version="schema-v1",
                policy_version="policy-v1",
            )
            self.assertEqual(gateway.generate(request), gateway.generate(request))

    def test_outbox_is_local_mock_only(self):
        outbox = LocalMockOutbox()
        self.assertEqual(outbox.backend, "in_process_mock")
        self.assertEqual(outbox.destination(), "local-mock-outbox")

from django.test import SimpleTestCase

from career_codesk.modules.ai_gateway.contracts import DeterministicFakeAiGateway
from career_codesk.modules.export.contracts import LocalMockOutbox


class AdapterTests(SimpleTestCase):
    def test_fake_ai_preview_is_repeatable_and_provisional(self):
        gateway = DeterministicFakeAiGateway()
        self.assertEqual(gateway.preview("capture-1"), gateway.preview("capture-1"))
        self.assertEqual(gateway.preview("capture-1").status, "provisional")
        self.assertEqual(gateway.preview("capture-1").policy_version, "ai-policy-foundation-v1")

    def test_outbox_is_local_mock_only(self):
        outbox = LocalMockOutbox()
        self.assertEqual(outbox.backend, "in_process_mock")
        self.assertEqual(outbox.destination(), "local-mock-outbox")

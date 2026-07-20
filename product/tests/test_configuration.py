from django.conf import settings
from django.test import SimpleTestCase


class ConfigurationTests(SimpleTestCase):
    def test_safe_local_defaults(self):
        self.assertEqual(settings.TIME_ZONE, "UTC")
        self.assertTrue(settings.SYNTHETIC_ONLY_MODE)
        self.assertEqual(settings.AI_ADAPTER, "deterministic_fake")
        self.assertEqual(settings.OUTBOX_BACKEND, "in_process_mock")
        self.assertFalse(settings.LIVE_INTEGRATIONS_ENABLED)
        self.assertEqual(settings.DATABASES["default"]["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(
            [host for host in settings.ALLOWED_HOSTS if host != "testserver"],
            ["localhost", "127.0.0.1", "[::1]"],
        )
        self.assertEqual(settings.ALLOWED_HOSTS.count("testserver"), 1)

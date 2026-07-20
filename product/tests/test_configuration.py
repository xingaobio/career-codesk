from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse


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

    def test_checked_in_stylesheet_is_served_with_safe_local_debug_setting(self):
        self.assertFalse(settings.DEBUG)
        response = self.client.get(
            reverse("local-static", kwargs={"path": "career_codesk/workbench.css"})
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/css")

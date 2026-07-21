"""Safe, deterministic settings for a loopback-only product demonstration."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# This is deliberately public and local-demo-only. It is not a credential.
SECRET_KEY = "career-codesk-public-local-demo-signing-key-not-a-secret"
DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "career_codesk.web",
    "career_codesk.modules.intake_provenance.apps.IntakeProvenanceConfig",
    "career_codesk.modules.casework.apps.CaseworkConfig",
    "career_codesk.modules.ai_gateway.apps.AiGatewayConfig",
    "career_codesk.modules.planning.apps.PlanningConfig",
    "career_codesk.modules.decisions.apps.DecisionsConfig",
    "career_codesk.modules.delivery_feedback.apps.DeliveryFeedbackConfig",
    "career_codesk.modules.export.apps.ExportConfig",
    "career_codesk.modules.audit.apps.AuditConfig",
]
MIDDLEWARE = ["django.middleware.csrf.CsrfViewMiddleware"]
ROOT_URLCONF = "career_codesk.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "career_codesk" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": ["django.template.context_processors.csrf"],
        },
    }
]
WSGI_APPLICATION = "career_codesk.wsgi.application"
ASGI_APPLICATION = "career_codesk.asgi.application"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get(
            "CAREER_CODESK_EVALUATION_SQLITE_PATH", BASE_DIR / "career_codesk.sqlite3"
        ),
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-gb"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = Path(os.environ.get("STATIC_ROOT", BASE_DIR / "static-build"))
STATICFILES_DIRS = [BASE_DIR / "career_codesk" / "static"]

# Explicit prototype controls. No setting enables a live service.
SYNTHETIC_ONLY_MODE = True
AI_ADAPTER = "deterministic_fake"
OUTBOX_BACKEND = "in_process_mock"
LIVE_INTEGRATIONS_ENABLED = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

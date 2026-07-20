import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase


class StartupTests(SimpleTestCase):
    def test_fresh_startup_renders_home_and_health_without_network_or_credentials(self):
        product_dir = Path(__file__).resolve().parents[1]
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"API_KEY", "DATABASE_URL", "DJANGO_SETTINGS_MODULE", "SECRET_KEY"}
        }
        environment["DJANGO_SETTINGS_MODULE"] = "career_codesk.settings"
        startup_script = """
import os
import socket

def deny_network(*args, **kwargs):
    raise AssertionError("network access is not permitted")

OriginalSocket = socket.socket

class DeniedSocket(OriginalSocket):
    def connect(self, *args, **kwargs):
        deny_network(*args, **kwargs)

    def connect_ex(self, *args, **kwargs):
        deny_network(*args, **kwargs)

socket.create_connection = deny_network
socket.socket = DeniedSocket
os.environ.pop("API_KEY", None)
os.environ.pop("DATABASE_URL", None)
os.environ.pop("SECRET_KEY", None)

import django
django.setup()
from django.test import Client

client = Client()
home = client.get("/")
health = client.get("/health/")
assert home.status_code == 200
assert b"Synthetic mock source" in home.content
assert b"Simulated identity only" in home.content
assert health.status_code == 200
assert health.content == b"ok"
"""
        result = subprocess.run(
            [sys.executable, "-c", startup_script],
            cwd=product_dir,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

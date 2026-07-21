import json
from pathlib import Path

from django.test import SimpleTestCase

from career_codesk.identity import available_actors


class FixtureTests(SimpleTestCase):
    def test_foundation_manifest_is_deterministic_and_synthetic(self):
        fixture_root = Path(__file__).resolve().parents[1] / "fixtures"
        manifest_path = fixture_root / "foundation-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["fixture_version"], "foundation-v1")
        self.assertEqual(manifest["schema_version"], "1.0")
        self.assertEqual(manifest["clock_utc"], "2026-01-01T00:00:00Z")
        self.assertEqual(manifest["seed"], 20260101)
        self.assertTrue(manifest["synthetic_data_attestation"])
        self.assertFalse(manifest["contains_learner_records"])
        self.assertEqual(manifest["source_label"], "Synthetic mock source — no MIS connection.")
        self.assertEqual(
            manifest["fixed_ids"], {actor.role: actor.id for actor in available_actors()}
        )

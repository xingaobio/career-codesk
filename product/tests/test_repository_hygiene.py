"""Guardrails for repository-wide credentials and synthetic rejection samples."""

import subprocess
from pathlib import Path

from django.test import SimpleTestCase

from career_codesk.modules.audit.evaluation import _hygiene_check


class RepositoryHygieneTests(SimpleTestCase):
    def test_scans_every_tracked_path_and_classifies_known_rejection_sentinels(self):
        result = _hygiene_check()
        repository_root = Path(__file__).resolve().parents[2]
        tracked_files = subprocess.run(
            ["git", "ls-files"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        self.assertTrue(result["passed"], result["unacceptable_findings"])
        self.assertEqual(result["files_scanned"], len(tracked_files))
        sample_files = [
            path
            for path in tracked_files
            if path.startswith("product/fixtures/")
            or path.startswith("product/tests/")
            or path.startswith("product/DEMO_")
        ]
        self.assertEqual(result["sample_data_files_scanned"], len(sample_files))
        classifications = {
            (item["file"], item["kind"], item["classification"])
            for item in result["classified_sentinels"]
        }
        expected = {
            (
                "product/fixtures/intake/disallowed.csv",
                "email",
                "synthetic_rejection_sentinel",
            ),
            (
                "product/tests/test_synthetic_intake.py",
                "labelled_name",
                "synthetic_rejection_sentinel",
            ),
            (
                "product/tests/test_synthetic_intake.py",
                "date_of_birth",
                "synthetic_rejection_sentinel",
            ),
            (
                "product/tests/test_synthetic_intake.py",
                "street_address",
                "synthetic_rejection_sentinel",
            ),
            (
                "product/tests/test_synthetic_intake.py",
                "mobile",
                "synthetic_rejection_sentinel",
            ),
        }
        self.assertTrue(expected.issubset(classifications))

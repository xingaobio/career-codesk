"""Focused checks for the local, deterministic eight-scenario evidence pack."""

import json
from pathlib import Path

from django.test import TestCase

from career_codesk.modules.audit.evaluation import SCENARIO_KEYS, run_evaluation


class EvaluationDemoTests(TestCase):
    def test_manifest_declares_each_required_scenario_once(self):
        product_dir = Path(__file__).resolve().parents[1]
        manifest = json.loads(
            (product_dir / "fixtures" / "evaluation" / "scenarios-v1.json").read_text()
        )
        self.assertEqual(tuple(item["key"] for item in manifest["scenarios"]), SCENARIO_KEYS)
        self.assertEqual(len({item["key"] for item in manifest["scenarios"]}), len(SCENARIO_KEYS))

    def test_evaluator_runs_all_scenarios_with_stable_alias_only_report(self):
        report = run_evaluation()
        self.assertEqual(report["scenario_order"], list(SCENARIO_KEYS))
        self.assertTrue(all(item["passed"] for item in report["scenarios"].values()))
        self.assertTrue(all(item["passed"] for item in report["checks"].values()))
        self.assertEqual(report["scenarios"]["ai-failure"]["disposition"], "adapter_error")
        self.assertEqual(
            report["scenarios"]["reopen"]["transitions"],
            ["open>active", "active>closed", "closed>open"],
        )
        encoded = json.dumps(report, sort_keys=True)
        self.assertNotIn("synthetic-eval-happy-001", encoded)
        self.assertNotIn("created_at", encoded)

    def test_runner_uses_only_named_disposable_targets_and_socket_guard(self):
        product_dir = Path(__file__).resolve().parents[1]
        script = (product_dir / "scripts" / "run-demo-evaluation.sh").read_text()
        self.assertIn("evaluation-v1.sqlite3", script)
        self.assertIn("report-v1.json", script)
        self.assertIn("socket.create_connection = deny_network", script)
        self.assertIn("CAREER_CODESK_UV_CACHE_DIR", script)
        self.assertIn('call_command("evaluate_demo", "--all"', script)

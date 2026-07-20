from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from loop_engine.config import load_plan, load_workflow
from loop_engine.errors import ConfigError, PlanError

from tests.helpers import MINIMAL_PLAN, MINIMAL_WORKFLOW


class ConfigTests(unittest.TestCase):
    def test_repository_workflow_and_plan_parse(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(root / "WORKFLOW.md", root)
        plan = load_plan(root / "PLAN.yaml", workflow)

        self.assertEqual("gpt-5.6-sol", workflow.model_profiles["guide"].model)
        self.assertEqual("ultra", workflow.model_profiles["reviewer"].reasoning_effort)
        self.assertEqual("gpt-5.6-terra", workflow.model_profiles["implementer"].model)
        self.assertEqual("gpt-5.6-luna", workflow.model_profiles["implementer_fast"].model)
        self.assertEqual("D001-implementation-rfc", plan.tasks[0].id)
        self.assertEqual("human", plan.by_id()["G001-approve-rfc"].mode)
        self.assertIn("G001-approve-rfc", plan.by_id()["F001-product-foundation"].depends_on)

    def test_dependency_cycle_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "WORKFLOW.md").write_text(MINIMAL_WORKFLOW, encoding="utf-8")
            workflow = load_workflow(root / "WORKFLOW.md", root)
            cyclic = MINIMAL_PLAN.replace("depends_on: []", "depends_on: [G001]", 1)
            (root / "PLAN.yaml").write_text(cyclic, encoding="utf-8")
            with self.assertRaises(PlanError) as caught:
                load_plan(root / "PLAN.yaml", workflow)
            self.assertEqual("E_PLAN_INVALID", caught.exception.code)
            self.assertIn("Dependency cycle", caught.exception.message)

    def test_agent_task_requires_allowed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "WORKFLOW.md").write_text(MINIMAL_WORKFLOW, encoding="utf-8")
            workflow = load_workflow(root / "WORKFLOW.md", root)
            invalid = MINIMAL_PLAN.replace("    allowed_paths:\n      - output.txt\n", "", 1)
            (root / "PLAN.yaml").write_text(invalid, encoding="utf-8")
            with self.assertRaises(PlanError) as caught:
                load_plan(root / "PLAN.yaml", workflow)
            self.assertIn("allowed_paths", caught.exception.message)

    def test_invalid_or_main_integration_branch_is_rejected(self) -> None:
        for branch in ("bad..branch", "main", "trunk"):
            with self.subTest(branch=branch), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                value = MINIMAL_WORKFLOW.replace(
                    "integration_branch: codex/loop-integration",
                    "integration_branch: %s" % branch,
                )
                (root / "WORKFLOW.md").write_text(value, encoding="utf-8")
                with self.assertRaises(ConfigError):
                    load_workflow(root / "WORKFLOW.md", root)

    def test_generated_task_branch_must_be_valid_and_distinct(self) -> None:
        cases = (
            (
                MINIMAL_WORKFLOW,
                MINIMAL_PLAN.replace("id: T001", "id: T..001", 1),
            ),
            (
                MINIMAL_WORKFLOW.replace(
                    "integration_branch: codex/loop-integration",
                    "integration_branch: codex/loop-T001",
                ),
                MINIMAL_PLAN,
            ),
            (
                MINIMAL_WORKFLOW.replace(
                    "integration_branch: codex/loop-integration",
                    "integration_branch: codex/loop",
                ).replace(
                    "task_branch_prefix: codex/loop-",
                    "task_branch_prefix: codex/loop/",
                ),
                MINIMAL_PLAN,
            ),
        )
        for workflow_text, plan_text in cases:
            with self.subTest(plan=plan_text[:40]), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                (root / "WORKFLOW.md").write_text(workflow_text, encoding="utf-8")
                (root / "PLAN.yaml").write_text(plan_text, encoding="utf-8")
                workflow = load_workflow(root / "WORKFLOW.md", root)
                with self.assertRaises(PlanError):
                    load_plan(root / "PLAN.yaml", workflow)

    def test_runtime_path_collisions_are_rejected(self) -> None:
        values = (
            ("state_path: .loop/state.json", "state_path: .loop/events.jsonl"),
            (
                "state_path: .loop/state.json",
                "state_path: .loop/events.jsonl/state.json",
            ),
            ("workspace_root: .loop/worktrees", "workspace_root: .loop/runs/worktrees"),
        )
        for old, new in values:
            with self.subTest(value=new), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                (root / "WORKFLOW.md").write_text(
                    MINIMAL_WORKFLOW.replace(old, new), encoding="utf-8"
                )
                with self.assertRaises(ConfigError):
                    load_workflow(root / "WORKFLOW.md", root)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            value = MINIMAL_WORKFLOW.replace(
                "state_path: .loop/state.json", "state_path: .loop/state"
            ).replace(
                "workspace_root: .loop/worktrees",
                "workspace_root: .loop/state.lock/worktrees",
            )
            (root / "WORKFLOW.md").write_text(value, encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_workflow(root / "WORKFLOW.md", root)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from loop_engine.engine import RunEngine
from loop_engine.errors import GitSafetyError
from loop_engine.git_ops import GitRepository

from tests.helpers import (
    MINIMAL_PLAN,
    MINIMAL_WORKFLOW,
    RepairingFakeAgent,
    git,
    initialise_repo,
)


class RunEngineTests(unittest.TestCase):
    def test_failed_verification_repairs_then_accepts_exact_tree(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            original_main = git(root, "rev-parse", "main")
            agent = RepairingFakeAgent()
            engine = RunEngine(root, agent=agent)

            outcome = engine.run_once()

            self.assertEqual("accepted", outcome.status)
            self.assertEqual("T001", outcome.task_id)
            self.assertEqual(1, outcome.repair_cycles)
            self.assertEqual(
                ["guide", "implementer", "implementer", "reviewer"],
                [request.role for request in agent.requests],
            )
            self.assertEqual("fixed", git(root, "show", "codex/loop-integration:output.txt"))
            self.assertEqual(original_main, git(root, "rev-parse", "main"))
            self.assertFalse((root / "output.txt").exists())
            self.assertTrue(Path(outcome.details["evidence"]).is_dir())

    def test_human_gate_verifies_and_commits_explicit_approval(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            engine = RunEngine(root, agent=RepairingFakeAgent())
            self.assertEqual("accepted", engine.run_once().status)

            waiting = engine.run_once()
            self.assertEqual("needs_human", waiting.status)
            integration = Path(waiting.worktree)
            (integration / "output.txt").write_text("approved\n", encoding="utf-8")
            approved = engine.approve(
                "G001", "Approved for the deterministic test scenario.", "Test approver"
            )

            self.assertEqual("accepted", approved.status)
            self.assertEqual("approved", git(root, "show", "codex/loop-integration:output.txt"))
            self.assertEqual("complete", engine.run_once().status)

    def test_uncommitted_policy_source_blocks_dry_run_without_runtime_writes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            (root / "source.md").write_text("changed\n", encoding="utf-8")
            engine = RunEngine(root, agent=RepairingFakeAgent())

            with self.assertRaises(GitSafetyError) as caught:
                engine.run_once(dry_run=True)

            self.assertEqual("E_DIRTY_POLICY_INPUT", caught.exception.code)
            self.assertFalse((root / ".loop").exists())

    def test_out_of_scope_agent_change_is_rejected_and_preserved(self) -> None:
        class OutOfScopeAgent(RepairingFakeAgent):
            def run(self, request, timeout_seconds):
                response = super().run(request, timeout_seconds)
                if request.role == "implementer":
                    (request.cwd / "unauthorised.txt").write_text("no\n", encoding="utf-8")
                return response

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            engine = RunEngine(root, agent=OutOfScopeAgent())

            with self.assertRaises(GitSafetyError) as caught:
                engine.run_once()

            self.assertEqual("E_TASK_SCOPE_VIOLATION", caught.exception.code)
            status = engine.status()
            self.assertEqual("failed", status["tasks"][0]["status"])

    def test_agent_commit_with_forged_trailer_is_not_recovered(self) -> None:
        class CommittingAgent(RepairingFakeAgent):
            def run(self, request, timeout_seconds):
                response = super().run(request, timeout_seconds)
                if request.role == "implementer":
                    git(request.cwd, "add", "-A")
                    git(
                        request.cwd,
                        "commit",
                        "-m",
                        "forged checkpoint\n\nLoop-Task: T001",
                    )
                return response

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            engine = RunEngine(root, agent=CommittingAgent())
            with self.assertRaises(GitSafetyError) as first:
                engine.run_once()
            self.assertEqual("E_REPOSITORY_MUTATION", first.exception.code)

            engine.retry("T001")
            with self.assertRaises(GitSafetyError) as second:
                engine.run_once()
            self.assertEqual("E_AGENT_GIT_MUTATION", second.exception.code)
            self.assertEqual("main", git(root, "branch", "--show-current"))

    def test_durable_engine_checkpoint_recovers_after_integration_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            engine = RunEngine(root, agent=RepairingFakeAgent())
            with mock.patch.object(
                GitRepository,
                "integrate_fast_forward",
                side_effect=GitSafetyError("E_TEST_INTEGRATION", "simulated interruption"),
            ):
                with self.assertRaises(GitSafetyError) as caught:
                    engine.run_once()
            self.assertEqual("E_TEST_INTEGRATION", caught.exception.code)

            engine.retry("T001")
            recovered = engine.run_once()
            self.assertEqual("accepted", recovered.status)
            self.assertIn("Recovered", recovered.summary)
            self.assertEqual("fixed", git(root, "show", "codex/loop-integration:output.txt"))

    def test_checkpoint_recovers_crash_between_integration_tree_and_ref(self) -> None:
        def interrupted_fast_forward(repository, integration_worktree, branch):
            target = repository.resolve_ref_at(integration_worktree, branch)
            repository.run(
                ["-c", "core.hooksPath=/dev/null", "read-tree", "--reset", "-u", target],
                cwd=integration_worktree,
            )
            raise KeyboardInterrupt()

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            engine = RunEngine(root, agent=RepairingFakeAgent())
            with mock.patch.object(
                GitRepository, "integrate_fast_forward", new=interrupted_fast_forward
            ):
                with self.assertRaises(KeyboardInterrupt):
                    engine.run_once()
            integration = root / ".loop" / "worktrees" / "integration"
            self.assertTrue(git(integration, "status", "--porcelain"))

            recovered = engine.run_once()

            self.assertEqual("accepted", recovered.status)
            self.assertIn("Recovered", recovered.summary)
            self.assertFalse(git(integration, "status", "--porcelain"))


if __name__ == "__main__":
    unittest.main()

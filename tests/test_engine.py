from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from loop_engine.engine import RunEngine
from loop_engine.errors import GitSafetyError, RunFailed
from loop_engine.git_ops import GitRepository
from loop_engine.models import AgentResponse

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
            first_verification = json.loads(
                (Path(outcome.details["evidence"]) / "cycle-00" / "verification.json").read_text(
                    encoding="utf-8"
                )
            )
            first_commands = first_verification["stability_passes"][0]["commands"]
            self.assertEqual(1, len(first_commands))
            self.assertIn("grep -q", first_commands[0]["command"])

    def test_nonblocking_review_findings_are_deferred_without_repair(self) -> None:
        class NonBlockingReviewAgent(RepairingFakeAgent):
            def run(self, request, timeout_seconds):
                response = super().run(request, timeout_seconds)
                if request.role == "implementer":
                    (request.cwd / "output.txt").write_text("fixed\n", encoding="utf-8")
                if request.role != "reviewer":
                    return response
                output = {
                    "verdict": "repair",
                    "summary": "A future hardening improvement is available.",
                    "findings": [
                        {
                            "severity": "important",
                            "criterion": "output.txt contains fixed.",
                            "message": "Add another defensive test later.",
                            "repair": "Add the test in a later hardening task.",
                        }
                    ],
                    "questions": [],
                }
                response.last_message_path.write_text(
                    json.dumps(output), encoding="utf-8"
                )
                return AgentResponse(
                    request.role,
                    output,
                    response.last_message_path,
                    response.stdout_path,
                    response.stderr_path,
                )

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            agent = NonBlockingReviewAgent()

            outcome = RunEngine(root, agent=agent).run_once()

            self.assertEqual("accepted", outcome.status)
            self.assertEqual(1, agent.implementer_calls)
            self.assertEqual(
                ["guide", "implementer", "reviewer"],
                [request.role for request in agent.requests],
            )
            review = json.loads(
                (Path(outcome.details["evidence"]) / "cycle-00" / "review.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("repair", review["verdict"])
            self.assertEqual("accept", review["effective_verdict"])

    def test_reject_without_valid_blocker_is_deferred_without_stopping_delivery(self) -> None:
        class NonBlockingRejectAgent(RepairingFakeAgent):
            def run(self, request, timeout_seconds):
                response = super().run(request, timeout_seconds)
                if request.role == "implementer":
                    (request.cwd / "output.txt").write_text("fixed\n", encoding="utf-8")
                if request.role != "reviewer":
                    return response
                output = {
                    "verdict": "reject",
                    "summary": "Reviewer attempted to expand into a future architecture audit.",
                    "findings": [
                        {
                            "severity": "important",
                            "criterion": "Add a future plugin security framework.",
                            "message": "Not part of this delivery slice.",
                            "repair": "Defer to a separately authorised task.",
                        }
                    ],
                    "questions": [],
                }
                response.last_message_path.write_text(json.dumps(output), encoding="utf-8")
                return AgentResponse(
                    request.role,
                    output,
                    response.last_message_path,
                    response.stdout_path,
                    response.stderr_path,
                )

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            agent = NonBlockingRejectAgent()

            outcome = RunEngine(root, agent=agent).run_once()

            self.assertEqual("accepted", outcome.status)
            self.assertEqual(1, agent.implementer_calls)
            review = json.loads(
                (Path(outcome.details["evidence"]) / "cycle-00" / "review.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("reject", review["verdict"])
            self.assertEqual("accept", review["effective_verdict"])

    def test_autonomous_review_repair_is_capped_and_retry_is_targeted(self) -> None:
        class BoundedReviewAgent(RepairingFakeAgent):
            def __init__(self):
                super().__init__()
                self.reviewer_calls = 0

            def run(self, request, timeout_seconds):
                response = super().run(request, timeout_seconds)
                if request.role == "implementer":
                    (request.cwd / "output.txt").write_text("fixed\n", encoding="utf-8")
                if request.role != "reviewer":
                    return response
                self.reviewer_calls += 1
                if self.reviewer_calls <= 2:
                    output = {
                        "verdict": "repair",
                        "summary": "The acceptance criterion still needs one bounded fix.",
                        "findings": [
                            {
                                "severity": "blocking",
                                "criterion": "output.txt contains fixed.",
                                "message": "Simulated blocking acceptance gap.",
                                "repair": "Apply the single bounded fix.",
                            }
                        ],
                        "questions": [],
                    }
                else:
                    output = {
                        "verdict": "accept",
                        "summary": "The targeted repair now satisfies acceptance.",
                        "findings": [],
                        "questions": [],
                    }
                response.last_message_path.write_text(
                    json.dumps(output), encoding="utf-8"
                )
                return AgentResponse(
                    request.role,
                    output,
                    response.last_message_path,
                    response.stdout_path,
                    response.stderr_path,
                )

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            agent = BoundedReviewAgent()
            engine = RunEngine(root, agent=agent)

            with self.assertRaises(RunFailed) as exhausted:
                engine.run_once()

            self.assertEqual("E_REPAIR_EXHAUSTED", exhausted.exception.code)
            self.assertEqual(2, agent.implementer_calls)
            self.assertEqual(2, agent.reviewer_calls)
            first_run_id = engine.status()["tasks"][0]["run_id"]

            retry = engine.retry("T001", "Authorise one targeted acceptance repair.")
            outcome = engine.run_once()

            self.assertIn("targeted", retry.summary.lower())
            self.assertEqual("accepted", outcome.status)
            self.assertEqual(first_run_id, outcome.run_id)
            self.assertEqual(1, len([r for r in agent.requests if r.role == "guide"]))
            self.assertEqual(3, agent.implementer_calls)
            implementer_sessions = {
                request.session_path for request in agent.requests if request.role == "implementer"
            }
            reviewer_sessions = {
                request.session_path for request in agent.requests if request.role == "reviewer"
            }
            self.assertEqual(1, len(implementer_sessions))
            self.assertNotIn(None, implementer_sessions)
            self.assertEqual(1, len(reviewer_sessions))
            self.assertNotIn(None, reviewer_sessions)

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

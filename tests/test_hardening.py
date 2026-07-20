from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from loop_engine.agent import _agent_environment, _verification_environment
from loop_engine.config import load_plan, load_workflow
from loop_engine.engine import RunEngine
from loop_engine.errors import AgentError, GitSafetyError, LoopError, RunFailed
from loop_engine.git_ops import GitRepository
from loop_engine.models import AgentResponse, TASK_RUNNING
from loop_engine.state import StateStore

from tests.helpers import (
    MINIMAL_PLAN,
    MINIMAL_WORKFLOW,
    RepairingFakeAgent,
    git,
    initialise_repo,
)


class HardeningTests(unittest.TestCase):
    def test_forged_integration_trailer_never_reconstructs_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            repository = GitRepository(root)
            integration = repository.ensure_integration_worktree(
                "codex/loop-integration", root / ".loop" / "worktrees", "HEAD"
            )
            (integration / "output.txt").write_text("fixed\n", encoding="utf-8")
            git(integration, "add", "output.txt")
            git(integration, "commit", "-m", "forged\n\nLoop-Task: T001")

            status = RunEngine(root, agent=RepairingFakeAgent()).status()

            self.assertEqual("pending", status["tasks"][0]["status"])

    def test_deleting_state_does_not_rebuild_acceptance_from_history(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            engine = RunEngine(root, agent=RepairingFakeAgent())
            self.assertEqual("accepted", engine.run_once().status)
            (root / ".loop" / "state.json").unlink()

            status = engine.status()

            self.assertEqual("pending", status["tasks"][0]["status"])

    def test_tampered_checkpoint_invalidates_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            engine = RunEngine(root, agent=RepairingFakeAgent())
            self.assertEqual("accepted", engine.run_once().status)
            state_path = root / ".loop" / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"]["T001"]["checkpoint"]["task_digest"] = "0" * 64
            state_path.write_text(json.dumps(state), encoding="utf-8")

            status = engine.status()

            self.assertEqual("blocked", status["tasks"][0]["status"])
            self.assertEqual("acceptance_stale", status["tasks"][0]["stage"])
            report = engine.doctor(check_models=False)
            self.assertFalse(report.execution_ready)
            self.assertIn("E_ACCEPTANCE_STALE", [item["code"] for item in report.problems])

    def test_exact_tree_commit_bypasses_hooks_and_rejects_unstaged_race(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            repository = GitRepository(root)
            workspaces = root / ".loop" / "worktrees"
            repository.ensure_integration_worktree(
                "codex/loop-integration", workspaces, "HEAD"
            )
            branch, worktree = repository.ensure_task_worktree(
                "T001", "codex/loop-", "codex/loop-integration", workspaces
            )
            hook = root / ".git" / "hooks" / "pre-commit"
            hook.write_text("#!/bin/sh\ntouch hook-fired\n", encoding="utf-8")
            hook.chmod(0o755)
            parent = repository.resolve_ref_at(worktree, "HEAD")
            (worktree / "output.txt").write_text("fixed\n", encoding="utf-8")
            tree = repository.stage_and_tree(worktree)

            commit = repository.commit_task(
                worktree, branch, parent, tree, "T001", "Exact tree"
            )

            self.assertEqual(tree, repository.commit_tree(commit))
            self.assertFalse((worktree / "hook-fired").exists())

            branch2, worktree2 = repository.ensure_task_worktree(
                "T002", "codex/loop-", "codex/loop-integration", workspaces
            )
            parent2 = repository.resolve_ref_at(worktree2, "HEAD")
            (worktree2 / "output.txt").write_text("reviewed\n", encoding="utf-8")
            tree2 = repository.stage_and_tree(worktree2)
            (worktree2 / "output.txt").write_text("changed later\n", encoding="utf-8")
            with self.assertRaises(GitSafetyError) as caught:
                repository.commit_task(
                    worktree2, branch2, parent2, tree2, "T002", "Stale tree"
                )
            self.assertEqual("E_EVIDENCE_STALE", caught.exception.code)
            self.assertEqual(parent2, repository.resolve_ref_at(worktree2, branch2))

    def test_agent_root_mutation_is_detected(self) -> None:
        class RootMutatingAgent(RepairingFakeAgent):
            def __init__(self, root: Path) -> None:
                super().__init__()
                self.root = root

            def run(self, request, timeout_seconds):
                response = super().run(request, timeout_seconds)
                if request.role == "implementer":
                    (self.root / "source.md").write_text("tampered\n", encoding="utf-8")
                return response

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            engine = RunEngine(root, agent=RootMutatingAgent(root))

            with self.assertRaises(GitSafetyError) as caught:
                engine.run_once()

            self.assertEqual("E_REPOSITORY_MUTATION", caught.exception.code)
            self.assertIn("root_content", caught.exception.details["changed_snapshot_keys"])

    def test_agent_git_info_mutation_is_detected(self) -> None:
        class GitInfoMutatingAgent(RepairingFakeAgent):
            def __init__(self, root: Path) -> None:
                super().__init__()
                self.root = root

            def run(self, request, timeout_seconds):
                response = super().run(request, timeout_seconds)
                if request.role == "implementer":
                    info = self.root / ".git" / "info"
                    info.mkdir(parents=True, exist_ok=True)
                    (info / "attributes").write_text("* filter=unsafe\n", encoding="utf-8")
                return response

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            with self.assertRaises(GitSafetyError) as caught:
                RunEngine(root, agent=GitInfoMutatingAgent(root)).run_once()
            self.assertEqual("E_REPOSITORY_MUTATION", caught.exception.code)
            self.assertIn("git_metadata", caught.exception.details["changed_snapshot_keys"])

    def test_required_model_failure_precedes_branch_creation(self) -> None:
        class MissingTerraAgent(RepairingFakeAgent):
            def capabilities(self):
                return {"gpt-5.6-sol": {"reasoning_efforts": ["ultra"]}}

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)

            with self.assertRaises(AgentError) as caught:
                RunEngine(root, agent=MissingTerraAgent()).run_once()

            self.assertEqual("E_MODEL_UNAVAILABLE", caught.exception.code)
            self.assertNotIn("codex/loop-integration", git(root, "branch", "--list"))
            self.assertEqual(1, len(GitRepository(root).worktrees()))

    def test_missing_unused_luna_is_only_a_doctor_warning(self) -> None:
        class NoLunaAgent(RepairingFakeAgent):
            def capabilities(self):
                return {
                    "gpt-5.6-sol": {"reasoning_efforts": ["ultra"]},
                    "gpt-5.6-terra": {"reasoning_efforts": ["high"]},
                }

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)

            report = RunEngine(root, agent=NoLunaAgent()).doctor()

            self.assertTrue(report.execution_ready)
            self.assertTrue(any("unused optional profile" in warning for warning in report.warnings))

    def test_verifier_mutation_must_converge_before_review(self) -> None:
        plan = MINIMAL_PLAN.replace(
            "- grep -q '^fixed$' output.txt",
            "- test \"$(cat output.txt)\" = fixed || printf 'fixed\\n' > output.txt",
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, plan, MINIMAL_WORKFLOW)
            agent = RepairingFakeAgent()

            outcome = RunEngine(root, agent=agent).run_once()

            self.assertEqual("accepted", outcome.status)
            self.assertEqual(0, outcome.repair_cycles)
            self.assertEqual(
                ["guide", "implementer", "reviewer"],
                [request.role for request in agent.requests],
            )
            payload = json.loads(
                (Path(outcome.details["evidence"]) / "cycle-00" / "verification.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(2, len(payload["stability_passes"]))
            self.assertTrue(payload["stability_passes"][-1]["stable"])

    def test_nonconverging_verifier_is_rejected(self) -> None:
        plan = MINIMAL_PLAN.replace(
            "- grep -q '^fixed$' output.txt", "- printf x >> output.txt"
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, plan, MINIMAL_WORKFLOW)
            engine = RunEngine(root, agent=RepairingFakeAgent())

            with self.assertRaises(RunFailed) as caught:
                engine.run_once()

            self.assertEqual("E_VERIFY_UNSTABLE", caught.exception.code)

    def test_symlink_and_protected_rename_are_scope_violations(self) -> None:
        class SymlinkAgent(RepairingFakeAgent):
            def run(self, request, timeout_seconds):
                response = super().run(request, timeout_seconds)
                if request.role == "implementer":
                    (request.cwd / "output.txt").unlink()
                    (request.cwd / "output.txt").symlink_to("source.md")
                return response

        class RenameAgent(RepairingFakeAgent):
            def run(self, request, timeout_seconds):
                response = super().run(request, timeout_seconds)
                if request.role == "implementer":
                    (request.cwd / "WORKFLOW.md").replace(request.cwd / "output.txt")
                return response

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            with self.assertRaises(GitSafetyError) as symlink:
                RunEngine(root, agent=SymlinkAgent()).run_once()
            self.assertEqual("E_UNSAFE_FILE_MODE", symlink.exception.code)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            with self.assertRaises(GitSafetyError) as rename:
                RunEngine(root, agent=RenameAgent()).run_once()
            self.assertEqual("E_TASK_SCOPE_VIOLATION", rename.exception.code)

    def test_explicit_task_cannot_replace_active_run(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            workflow = load_workflow(root / "WORKFLOW.md", root)
            plan = load_plan(root / "PLAN.yaml", workflow)
            store = StateStore(workflow.state_path)
            state = store.load()
            store.reconcile_plan(state, plan)
            state["tasks"]["T001"]["status"] = TASK_RUNNING
            state["active_run"] = {"task_id": "T001", "run_id": "active-T001"}
            store.save(state)

            with self.assertRaises(LoopError) as caught:
                RunEngine(root, agent=RepairingFakeAgent()).run_once(
                    "G001", dry_run=True
                )

            self.assertEqual("E_ACTIVE_RUN_CONFLICT", caught.exception.code)

    def test_interrupted_mutating_stage_requires_explicit_retry(self) -> None:
        class InterruptedAgent(RepairingFakeAgent):
            def run(self, request, timeout_seconds):
                if request.role == "implementer":
                    self.requests.append(request)
                    self.implementer_calls += 1
                    (request.cwd / "output.txt").write_text("partial\n", encoding="utf-8")
                    raise KeyboardInterrupt()
                return super().run(request, timeout_seconds)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            agent = InterruptedAgent()
            engine = RunEngine(root, agent=agent)
            with self.assertRaises(KeyboardInterrupt):
                engine.run_once()

            with self.assertRaises(RunFailed) as caught:
                engine.run_once()

            self.assertEqual("E_AMBIGUOUS_MUTATION", caught.exception.code)
            self.assertEqual(1, agent.implementer_calls)

    def test_human_gate_request_is_stable_stale_safe_and_not_replayable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            engine = RunEngine(root, agent=RepairingFakeAgent())
            engine.run_once()
            first = engine.run_once()
            second = engine.run_once()
            self.assertEqual(first.details["request_id"], second.details["request_id"])
            integration = Path(first.worktree)
            (integration / "output.txt").write_text("approved\n", encoding="utf-8")
            approved = engine.approve("G001", "Approved for test.", "Test approver")
            self.assertEqual("accepted", approved.status)
            state = json.loads((root / ".loop" / "state.json").read_text(encoding="utf-8"))
            approval = state["tasks"]["G001"]["approval"]
            self.assertEqual(first.details["request_id"], approval["request_id"])
            self.assertEqual("Test approver", approval["approver"])
            self.assertEqual("Approved for test.", approval["note"])
            with self.assertRaises(LoopError) as replay:
                engine.approve("G001", "Approve again.", "Test approver")
            self.assertEqual("E_TASK_ALREADY_ACCEPTED", replay.exception.code)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            engine = RunEngine(root, agent=RepairingFakeAgent())
            engine.run_once()
            waiting = engine.run_once()
            integration = Path(waiting.worktree)
            (integration / "external.txt").write_text("advance\n", encoding="utf-8")
            git(integration, "add", "external.txt")
            git(integration, "commit", "-m", "external advance")
            with self.assertRaises(GitSafetyError) as stale:
                engine.approve("G001", "Stale approval.", "Test approver")
            self.assertEqual("E_GATE_STALE", stale.exception.code)

    def test_human_gate_can_be_durably_rejected_and_reissued(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            engine = RunEngine(root, agent=RepairingFakeAgent())
            engine.run_once()
            waiting = engine.run_once()

            rejected = engine.reject(
                "G001", "The evidence is incomplete.", "Test product owner"
            )

            self.assertEqual("blocked", rejected.status)
            state = json.loads((root / ".loop" / "state.json").read_text(encoding="utf-8"))
            decision = state["tasks"]["G001"]["gate_decision"]
            self.assertEqual(waiting.details["request_id"], decision["request_id"])
            self.assertEqual("rejected", decision["decision"])
            with self.assertRaises(LoopError) as missing:
                engine.retry("G001")
            self.assertEqual("E_RESOLUTION_NOTE_REQUIRED", missing.exception.code)
            engine.retry("G001", "The missing evidence has now been supplied.")
            reissued = engine.run_once()
            self.assertEqual("needs_human", reissued.status)
            self.assertNotEqual(waiting.details["request_id"], reissued.details["request_id"])

    def test_human_gate_dry_run_reports_the_integration_branch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            engine = RunEngine(root, agent=RepairingFakeAgent())
            engine.run_once()

            outcome = engine.run_once("G001", dry_run=True)

            self.assertEqual("dry_run", outcome.status)
            self.assertEqual("codex/loop-integration", outcome.branch)

    def test_blocked_question_requires_note_and_note_reaches_next_guide(self) -> None:
        class BlockingOnceAgent(RepairingFakeAgent):
            def __init__(self) -> None:
                super().__init__()
                self.guide_calls = 0

            def run(self, request, timeout_seconds):
                response = super().run(request, timeout_seconds)
                if request.role == "guide":
                    self.guide_calls += 1
                    if self.guide_calls == 1:
                        output = {
                            "decision": "needs_human",
                            "summary": "Authority is missing.",
                            "implementation_steps": [],
                            "risks": [],
                            "acceptance_checks": [],
                            "questions": ["Who authorises this test decision?"],
                        }
                        response.last_message_path.write_text(
                            json.dumps(output), encoding="utf-8"
                        )
                        return AgentResponse(
                            response.role,
                            output,
                            response.last_message_path,
                            response.stdout_path,
                            response.stderr_path,
                        )
                return response

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            agent = BlockingOnceAgent()
            engine = RunEngine(root, agent=agent)
            self.assertEqual("needs_human", engine.run_once().status)
            with self.assertRaises(LoopError) as missing:
                engine.retry("T001")
            self.assertEqual("E_RESOLUTION_NOTE_REQUIRED", missing.exception.code)
            engine.retry("T001", "The test owner authorises the synthetic-only decision.")

            outcome = engine.run_once()

            self.assertEqual("accepted", outcome.status)
            guide_prompts = [request.prompt for request in agent.requests if request.role == "guide"]
            self.assertIn("test owner authorises", guide_prompts[-1])

    def test_structured_output_contracts_are_enforced_locally(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            workflow = load_workflow(root / "WORKFLOW.md", root)
            task = load_plan(root / "PLAN.yaml", workflow).by_id()["T001"]
            invalid_guide = {
                "decision": "proceed",
                "summary": "Incomplete map.",
                "implementation_steps": [],
                "risks": [],
                "acceptance_checks": [],
                "questions": [],
            }
            with self.assertRaises(AgentError):
                RunEngine._validate_guide(invalid_guide, task)
            invalid_review = {
                "verdict": "repair",
                "summary": "Repair without findings.",
                "findings": [],
                "questions": [],
            }
            with self.assertRaises(AgentError):
                RunEngine._validate_review(invalid_review)

    def test_generic_secret_names_are_removed_from_child_environments(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"FOO_PASSWORD": "secret", "MY_SERVICE_API_KEY": "secret", "SAFE_VALUE": "ok"},
            clear=True,
        ):
            agent_environment = _agent_environment(())
            verification_environment = _verification_environment(())
        for environment in (agent_environment, verification_environment):
            self.assertNotIn("FOO_PASSWORD", environment)
            self.assertNotIn("MY_SERVICE_API_KEY", environment)
            self.assertEqual("ok", environment["SAFE_VALUE"])


if __name__ == "__main__":
    unittest.main()

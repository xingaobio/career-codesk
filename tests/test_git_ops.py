from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from loop_engine.git_ops import GitRepository, workspace_key
from loop_engine.errors import GitSafetyError

from tests.helpers import MINIMAL_PLAN, MINIMAL_WORKFLOW, git, initialise_repo


class GitRepositoryTests(unittest.TestCase):
    def test_workspace_key_is_stable_and_collision_resistant(self) -> None:
        self.assertEqual("ABC-123", workspace_key("ABC-123"))
        self.assertNotEqual(workspace_key("A/B"), workspace_key("A B"))
        self.assertRegex(workspace_key("A/B"), r"^A_B-[0-9a-f]{16}$")

    def test_task_commit_fast_forwards_only_private_integration_branch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            original_main = git(root, "rev-parse", "main")
            repository = GitRepository(root)
            workspaces = root / ".loop" / "worktrees"
            integration = repository.ensure_integration_worktree(
                "codex/loop-integration", workspaces, "HEAD"
            )
            branch, task_worktree = repository.ensure_task_worktree(
                "A/B", "codex/loop-", "codex/loop-integration", workspaces
            )
            (task_worktree / "result.txt").write_text("accepted\n", encoding="utf-8")
            parent = repository.resolve_ref_at(task_worktree, "HEAD")
            reviewed_tree = repository.stage_and_tree(task_worktree)
            commit = repository.commit_task(
                task_worktree,
                branch,
                parent,
                reviewed_tree,
                "A/B",
                "Test task",
            )
            integrated = repository.integrate_fast_forward(integration, branch)

            self.assertEqual(commit, integrated)
            self.assertEqual(original_main, git(root, "rev-parse", "main"))
            self.assertEqual(parent, repository.commit_parent(commit))
            self.assertEqual(reviewed_tree, repository.commit_tree(commit))
            self.assertTrue(repository.is_ancestor(commit, integrated))
            self.assertEqual(
                "accepted",
                git(root, "show", "codex/loop-integration:result.txt"),
            )

    def test_worktree_file_collision_is_typed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialise_repo(root, MINIMAL_PLAN, MINIMAL_WORKFLOW)
            workspaces = root / ".loop" / "worktrees"
            workspaces.mkdir(parents=True)
            (workspaces / "integration").write_text("collision\n", encoding="utf-8")
            with self.assertRaises(GitSafetyError) as caught:
                GitRepository(root).ensure_integration_worktree(
                    "codex/loop-integration", workspaces, "HEAD"
                )
            self.assertEqual("E_WORKTREE_CONFLICT", caught.exception.code)


if __name__ == "__main__":
    unittest.main()

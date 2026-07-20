from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .errors import GitSafetyError


_SAFE_KEY = re.compile(r"[^A-Za-z0-9._-]")


def workspace_key(identifier: str) -> str:
    cleaned = _SAFE_KEY.sub("_", identifier)
    if cleaned == identifier:
        return cleaned
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:16]
    return "%s-%s" % (cleaned, digest)


class GitRepository:
    """Git/worktree Implementation kept behind the RunEngine seam."""

    def __init__(self, root: Path, timeout_seconds: int = 120) -> None:
        self.root = root.resolve()
        self.timeout_seconds = timeout_seconds

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Optional[Path] = None,
        check: bool = True,
        env: Optional[Mapping[str, str]] = None,
    ) -> subprocess.CompletedProcess:
        command = ["git"] + list(args)
        try:
            result = subprocess.run(
                command,
                cwd=str((cwd or self.root).resolve()),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                env=dict(env) if env is not None else None,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitSafetyError("E_GIT_FAILURE", "Git command failed to start: %s" % exc)
        if check and result.returncode != 0:
            reason = (result.stderr or result.stdout).strip()
            raise GitSafetyError(
                "E_GIT_FAILURE",
                "git %s failed: %s" % (" ".join(args), reason),
                details={"command": command, "returncode": result.returncode},
            )
        return result

    def validate_repository(self) -> None:
        result = self.run(["rev-parse", "--show-toplevel"])
        actual = Path(result.stdout.strip()).resolve()
        if actual != self.root:
            raise GitSafetyError(
                "E_REPOSITORY_ROOT",
                "Expected repository root %s, got %s" % (self.root, actual),
            )

    def resolve_ref(self, ref: str) -> str:
        return self.run(["rev-parse", "--verify", "%s^{commit}" % ref]).stdout.strip()

    def branch_exists(self, branch: str) -> bool:
        return self.run(["show-ref", "--verify", "--quiet", "refs/heads/%s" % branch], check=False).returncode == 0

    def path_tracked(self, path: str) -> bool:
        return self.run(["ls-files", "--error-unmatch", "--", path], check=False).returncode == 0

    def path_exists_at(self, ref: str, path: str) -> bool:
        return self.run(["cat-file", "-e", "%s:%s" % (ref, path)], check=False).returncode == 0

    def dirty_paths(self, paths: Sequence[str]) -> List[str]:
        if not paths:
            return []
        result = self.run(["status", "--porcelain=v1", "--untracked-files=all", "--"] + list(paths))
        dirty = []
        for line in result.stdout.splitlines():
            if len(line) >= 4:
                dirty.append(line[3:])
        return dirty

    def worktrees(self) -> Dict[str, str]:
        result = self.run(["worktree", "list", "--porcelain"])
        paths: Dict[str, str] = {}
        current_path = None
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                current_path = str(Path(line[9:]).resolve())
            elif line.startswith("branch refs/heads/") and current_path:
                paths[line[len("branch refs/heads/") :]] = current_path
            elif not line.strip():
                current_path = None
        return paths

    def ensure_integration_worktree(self, branch: str, workspace_root: Path, base_ref: str) -> Path:
        path = (workspace_root / "integration").resolve()
        self._require_under(path, workspace_root)
        worktrees = self.worktrees()
        existing = worktrees.get(branch)
        if existing:
            existing_path = Path(existing).resolve()
            self._require_under(existing_path, workspace_root)
            if existing_path != path:
                raise GitSafetyError(
                    "E_WORKTREE_CONFLICT",
                    "Integration branch %s is checked out at unexpected path %s"
                    % (branch, existing_path),
                )
            return existing_path
        self._prepare_parent(path.parent, "integration worktree")
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            raise GitSafetyError(
                "E_WORKTREE_CONFLICT",
                "Integration worktree path is not an empty directory: %s" % path,
            )
        if not self.branch_exists(branch):
            self.run(["branch", branch, self.resolve_ref(base_ref)])
        self.run(["worktree", "add", str(path), branch])
        return path

    def ensure_task_worktree(
        self,
        task_id: str,
        branch_prefix: str,
        integration_branch: str,
        workspace_root: Path,
    ) -> Tuple[str, Path]:
        key = workspace_key(task_id)
        branch = "%s%s" % (branch_prefix, key)
        path = (workspace_root / "tasks" / key).resolve()
        self._require_under(path, workspace_root)
        worktrees = self.worktrees()
        existing = worktrees.get(branch)
        if existing:
            existing_path = Path(existing).resolve()
            self._require_under(existing_path, workspace_root)
            if existing_path != path:
                raise GitSafetyError(
                    "E_WORKTREE_CONFLICT",
                    "Task branch %s is checked out at unexpected path %s"
                    % (branch, existing_path),
                )
            return branch, existing_path
        self._prepare_parent(path.parent, "task worktree")
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            raise GitSafetyError(
                "E_WORKTREE_CONFLICT",
                "Task worktree path is not an empty directory: %s" % path,
            )
        if not self.branch_exists(branch):
            self.run(["branch", branch, integration_branch])
        self.run(["worktree", "add", str(path), branch])
        return branch, path

    def has_changes(self, worktree: Path) -> bool:
        return bool(self.run(["status", "--porcelain=v1"], cwd=worktree).stdout.strip())

    def stage_and_tree(self, worktree: Path) -> str:
        self.run(["add", "-A"], cwd=worktree)
        return self.run(["write-tree"], cwd=worktree).stdout.strip()

    def changed_paths(self, worktree: Path, base_ref: str) -> List[str]:
        result = self.run(
            [
                "diff",
                "--cached",
                "--no-renames",
                "--name-only",
                "-z",
                "--diff-filter=ACDMRTUXB",
                base_ref,
            ],
            cwd=worktree,
        )
        return [path for path in result.stdout.split("\0") if path]

    def unsafe_index_paths(self, worktree: Path, paths: Sequence[str]) -> List[str]:
        if not paths:
            return []
        result = self.run(["ls-files", "-s", "-z", "--"] + list(paths), cwd=worktree)
        unsafe = []
        for entry in result.stdout.split("\0"):
            if not entry or "\t" not in entry:
                continue
            metadata, path = entry.split("\t", 1)
            mode = metadata.split(" ", 1)[0]
            if mode not in {"100644", "100755"}:
                unsafe.append(path)
        return unsafe

    def commit_task(
        self,
        worktree: Path,
        branch: str,
        parent: str,
        reviewed_tree: str,
        task_id: str,
        title: str,
    ) -> str:
        message = "loop(%s): %s\n\nLoop-Task: %s" % (task_id, title, task_id)
        return self._commit_exact_tree(
            worktree,
            branch,
            parent,
            reviewed_tree,
            message,
            author_name="Career CoDesk Loop",
            author_email="loop@career-codesk.local",
        )

    def integrate_fast_forward(self, integration_worktree: Path, branch: str) -> str:
        integration_branch = self.current_branch(integration_worktree)
        current = self.resolve_ref_at(integration_worktree, "HEAD")
        target = self.resolve_ref_at(integration_worktree, branch)
        ancestor = self.run(
            ["merge-base", "--is-ancestor", current, target],
            cwd=integration_worktree,
            check=False,
        )
        if ancestor.returncode != 0:
            raise GitSafetyError(
                "E_INTEGRATION_DIVERGED",
                "Cannot fast-forward %s from %s" % (integration_branch, branch),
            )
        prepared = self.has_changes(integration_worktree)
        if prepared:
            if (
                self.run(["write-tree"], cwd=integration_worktree).stdout.strip()
                != self.commit_tree(target)
                or not self._worktree_matches_index(integration_worktree)
            ):
                raise GitSafetyError(
                    "E_INTEGRATION_DIRTY",
                    "Integration worktree has changes that do not match %s" % target,
                )
        else:
            checkout = self.run(
                ["-c", "core.hooksPath=/dev/null", "read-tree", "--reset", "-u", target],
                cwd=integration_worktree,
                check=False,
            )
            if checkout.returncode != 0:
                self.run(
                    ["-c", "core.hooksPath=/dev/null", "read-tree", "--reset", "-u", current],
                    cwd=integration_worktree,
                    check=False,
                )
                raise GitSafetyError(
                    "E_INTEGRATION_TREE",
                    "Cannot materialize integration tree %s: %s"
                    % (target, (checkout.stderr or checkout.stdout).strip()),
                )
        advance = self.run(
            [
                "-c",
                "core.hooksPath=/dev/null",
                "update-ref",
                "refs/heads/%s" % integration_branch,
                target,
                current,
            ],
            cwd=integration_worktree,
            check=False,
        )
        if advance.returncode != 0:
            self.run(
                ["-c", "core.hooksPath=/dev/null", "read-tree", "--reset", "-u", current],
                cwd=integration_worktree,
                check=False,
            )
            raise GitSafetyError(
                "E_INTEGRATION_DIVERGED",
                "Integration ref changed while advancing %s" % integration_branch,
            )
        if self.has_changes(integration_worktree) or self.stage_and_tree(
            integration_worktree
        ) != self.commit_tree(target):
            self.run(
                [
                    "-c",
                    "core.hooksPath=/dev/null",
                    "update-ref",
                    "refs/heads/%s" % integration_branch,
                    current,
                    target,
                ],
                cwd=integration_worktree,
                check=False,
            )
            self.run(
                ["-c", "core.hooksPath=/dev/null", "read-tree", "--reset", "-u", current],
                cwd=integration_worktree,
                check=False,
            )
            raise GitSafetyError(
                "E_INTEGRATION_TREE",
                "Integration worktree does not exactly match %s" % target,
            )
        return target

    def commit_human_gate(
        self,
        integration_worktree: Path,
        branch: str,
        parent: str,
        reviewed_tree: str,
        task_id: str,
        title: str,
        note: str,
        approver: str,
    ) -> str:
        message = "gate(%s): %s\n\n%s\n\nLoop-Task: %s" % (task_id, title, note, task_id)
        return self._commit_exact_tree(
            integration_worktree,
            branch,
            parent,
            reviewed_tree,
            message,
            author_name=approver,
            author_email="human-gate@career-codesk.local",
        )

    def diff(self, worktree: Path, base_ref: str) -> str:
        return self.run(["diff", "--no-ext-diff", base_ref], cwd=worktree).stdout

    def current_branch(self, worktree: Path) -> str:
        return self.run(["symbolic-ref", "--quiet", "--short", "HEAD"], cwd=worktree).stdout.strip()

    def tree_at(self, worktree: Path, ref: str) -> str:
        return self.run(["rev-parse", "%s^{tree}" % ref], cwd=worktree).stdout.strip()

    def commit_tree(self, ref: str) -> str:
        return self.run(["rev-parse", "%s^{tree}" % ref]).stdout.strip()

    def commit_parent(self, ref: str) -> str:
        return self.run(["rev-parse", "%s^" % ref]).stdout.strip()

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return self.run(
            ["merge-base", "--is-ancestor", ancestor, descendant], check=False
        ).returncode == 0

    def safety_snapshot(self) -> Mapping[str, str]:
        return {
            "refs": self.run(
                ["for-each-ref", "--sort=refname", "--format=%(refname) %(objectname)"]
            ).stdout,
            "remotes": self.run(["remote", "-v"], check=False).stdout,
            "config": self.run(
                ["config", "--local", "--list", "--show-origin"], check=False
            ).stdout,
            "worktrees": self.run(["worktree", "list", "--porcelain"]).stdout,
            "root_status": self.run(
                ["status", "--porcelain=v1", "--untracked-files=all"]
            ).stdout,
            "root_content": self._root_content_digest(),
            "git_metadata": self._git_metadata_digest(),
        }

    def resolve_ref_at(self, worktree: Path, ref: str) -> str:
        return self.run(["rev-parse", "--verify", "%s^{commit}" % ref], cwd=worktree).stdout.strip()

    def _commit_exact_tree(
        self,
        worktree: Path,
        branch: str,
        parent: str,
        reviewed_tree: str,
        message: str,
        *,
        author_name: str,
        author_email: str,
    ) -> str:
        if self.current_branch(worktree) != branch:
            raise GitSafetyError("E_COMMIT_BRANCH", "Expected checked-out branch %s" % branch)
        if self.resolve_ref_at(worktree, "HEAD") != parent:
            raise GitSafetyError("E_COMMIT_PARENT", "Task parent changed before checkpoint")
        if self.run(["write-tree"], cwd=worktree).stdout.strip() != reviewed_tree:
            raise GitSafetyError("E_EVIDENCE_STALE", "Index no longer matches reviewed tree")
        if not self._worktree_matches_index(worktree):
            raise GitSafetyError(
                "E_EVIDENCE_STALE", "Worktree changed after the reviewed index was recorded"
            )
        env = dict(os.environ)
        env.update(
            {
                "GIT_AUTHOR_NAME": author_name,
                "GIT_AUTHOR_EMAIL": author_email,
                "GIT_COMMITTER_NAME": author_name,
                "GIT_COMMITTER_EMAIL": author_email,
            }
        )
        commit = self.run(
            [
                "-c",
                "core.hooksPath=/dev/null",
                "commit-tree",
                reviewed_tree,
                "-p",
                parent,
                "-m",
                message,
            ],
            cwd=worktree,
            env=env,
        ).stdout.strip()
        self.run(
            [
                "-c",
                "core.hooksPath=/dev/null",
                "update-ref",
                "refs/heads/%s" % branch,
                commit,
                parent,
            ],
            cwd=worktree,
            env=env,
        )
        if (
            self.resolve_ref_at(worktree, "HEAD") != commit
            or self.tree_at(worktree, commit) != reviewed_tree
            or self.resolve_ref_at(worktree, "%s^" % commit) != parent
            or self.has_changes(worktree)
        ):
            raise GitSafetyError(
                "E_COMMIT_TREE",
                "Engine checkpoint does not exactly match reviewed tree",
            )
        return commit

    def _root_content_digest(self) -> str:
        result = self.run(["ls-files", "-co", "--exclude-standard", "-z"])
        digest = hashlib.sha256()
        for relative in sorted(item for item in result.stdout.split("\0") if item):
            path = self.root / relative
            digest.update(relative.encode("utf-8", errors="surrogateescape"))
            try:
                mode = path.lstat().st_mode
            except OSError as exc:
                digest.update(("missing:%s" % exc.errno).encode("ascii"))
                continue
            digest.update(str(stat.S_IFMT(mode)).encode("ascii"))
            if stat.S_ISLNK(mode):
                digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
            elif stat.S_ISREG(mode):
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
        return digest.hexdigest()

    def _git_metadata_digest(self) -> str:
        raw = self.run(["rev-parse", "--git-common-dir"]).stdout.strip()
        common = Path(raw)
        if not common.is_absolute():
            common = (self.root / common).resolve()
        candidates = [
            path
            for path in common.iterdir()
            if path.is_file() or path.is_symlink()
        ]
        for relative in ("config", "config.worktree", "HEAD", "packed-refs", "index", "shallow"):
            path = common / relative
            if path.is_file() or path.is_symlink():
                candidates.append(path)
        for relative in ("hooks", "refs", "logs", "info", "objects/info"):
            folder = common / relative
            if folder.is_dir():
                candidates.extend(path for path in folder.rglob("*") if path.is_file() or path.is_symlink())
        linked = common / "worktrees"
        if linked.is_dir():
            for folder in linked.iterdir():
                if not folder.is_dir():
                    continue
                candidates.extend(
                    path
                    for path in folder.rglob("*")
                    if (path.is_file() or path.is_symlink()) and path.name != "index"
                )
        digest = hashlib.sha256()
        for path in sorted(set(candidates), key=lambda item: str(item)):
            relative = path.relative_to(common).as_posix()
            digest.update(relative.encode("utf-8"))
            if path.is_symlink():
                digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
            else:
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
        return digest.hexdigest()

    def _worktree_matches_index(self, worktree: Path) -> bool:
        if self.run(["diff", "--quiet"], cwd=worktree, check=False).returncode != 0:
            return False
        return not bool(
            self.run(
                ["ls-files", "--others", "--exclude-standard", "-z"], cwd=worktree
            ).stdout
        )

    @staticmethod
    def _require_under(path: Path, root: Path) -> None:
        path = path.resolve()
        root = root.resolve()
        try:
            path.relative_to(root)
        except ValueError:
            raise GitSafetyError(
                "E_WORKTREE_ESCAPE",
                "Workspace path %s escapes workspace root %s" % (path, root),
            )

    @staticmethod
    def _prepare_parent(path: Path, label: str) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise GitSafetyError(
                "E_WORKTREE_CONFLICT", "Cannot prepare %s parent %s: %s" % (label, path, exc)
            )
        if not path.is_dir():
            raise GitSafetyError(
                "E_WORKTREE_CONFLICT", "%s parent is not a directory: %s" % (label, path)
            )

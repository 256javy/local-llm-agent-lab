from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from llm_lab.core import LabError
from llm_lab.traces.repository import capture_repository_snapshot


GIT_AVAILABLE = shutil.which("git") is not None


@unittest.skipUnless(GIT_AVAILABLE, "Git no está disponible")
class RepositorySnapshotTests(unittest.TestCase):
    def git(self, directory: pathlib.Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", "-C", str(directory), *arguments], check=True, text=True, capture_output=True)

    def repository(self, temporary: str) -> pathlib.Path:
        root = pathlib.Path(temporary) / "repository"
        root.mkdir()
        self.git(root, "init")
        self.git(root, "config", "user.email", "tests@example.invalid")
        self.git(root, "config", "user.name", "Trace tests")
        (root / "tracked.txt").write_text("base\n", encoding="utf-8")
        self.git(root, "add", "tracked.txt")
        self.git(root, "commit", "-m", "initial")
        return root

    def test_clean_repository_captures_root_head_and_branch_without_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.repository(temporary)
            before = self.git(root, "status", "--porcelain=v2").stdout
            nested = root / "nested"
            nested.mkdir()

            snapshot = capture_repository_snapshot(nested)

            self.assertEqual(snapshot["state"], "captured")
            self.assertEqual(snapshot["repository"]["root"], str(root.resolve()))
            self.assertRegex(snapshot["head"]["value"], r"^[0-9a-f]{40}$")
            self.assertEqual(snapshot["ref"]["kind"], "branch")
            self.assertTrue(snapshot["status"]["summary"]["clean"])
            self.assertFalse(snapshot["status"]["summary"]["dirty"])
            self.assertEqual(snapshot["patches"]["staged"], "")
            self.assertEqual(snapshot["patches"]["unstaged"], "")
            self.assertEqual(snapshot["untracked"]["paths"], [])
            self.assertFalse(snapshot["untracked"]["contentIncluded"])
            self.assertEqual(self.git(root, "status", "--porcelain=v2").stdout, before)

    def test_dirty_staged_unstaged_and_untracked_evidence_is_complete_without_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.repository(temporary)
            (root / "tracked.txt").write_text("unstaged\n", encoding="utf-8")
            (root / "staged.txt").write_text("staged\n", encoding="utf-8")
            self.git(root, "add", "staged.txt")
            (root / "untracked-secret.txt").write_text("do-not-copy-this-content\n", encoding="utf-8")
            self.git(root, "remote", "add", "origin", "https://user:secret@example.invalid/owner/repository.git?token=secret")

            snapshot = capture_repository_snapshot(root)
            summary = snapshot["status"]["summary"]

            self.assertFalse(summary["clean"])
            self.assertTrue(summary["dirty"])
            self.assertTrue(summary["staged"])
            self.assertTrue(summary["unstaged"])
            self.assertTrue(summary["untracked"])
            self.assertIn("staged.txt", snapshot["patches"]["staged"])
            self.assertIn("tracked.txt", snapshot["patches"]["unstaged"])
            self.assertEqual(snapshot["untracked"]["paths"], ["untracked-secret.txt"])
            self.assertFalse(snapshot["untracked"]["contentIncluded"])
            serialized = json.dumps(snapshot)
            self.assertNotIn("do-not-copy-this-content", serialized)
            self.assertNotIn("user:secret", serialized)
            self.assertNotIn("token=secret", serialized)

    def test_detached_head_is_captured_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.repository(temporary)
            self.git(root, "checkout", "--detach", "HEAD")

            snapshot = capture_repository_snapshot(root)

            self.assertEqual(snapshot["ref"], {"state": "captured", "kind": "detached", "name": None})
            self.assertRegex(snapshot["head"]["value"], r"^[0-9a-f]{40}$")

    def test_non_git_directory_is_explicitly_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = capture_repository_snapshot(temporary)

            self.assertEqual(snapshot["state"], "unavailable")
            self.assertEqual(snapshot["repository"], {"state": "unavailable", "reason": "not_git_repository"})
            self.assertEqual(snapshot["patches"]["state"], "unavailable")

    def test_inferred_state_is_available_to_post_hoc_consumers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.repository(temporary)

            snapshot = capture_repository_snapshot(root, state="inferred")

            self.assertEqual(snapshot["state"], "inferred")
            self.assertEqual(snapshot["repository"]["state"], "inferred")
            self.assertEqual(snapshot["status"]["state"], "inferred")

    def test_permission_and_invalid_state_fail_as_lab_errors(self) -> None:
        def denied(_command: list[str]) -> subprocess.CompletedProcess[str]:
            raise PermissionError("denied")

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(LabError, "Permiso denegado"):
                capture_repository_snapshot(temporary, runner=denied)
            with self.assertRaisesRegex(LabError, "captured o inferred"):
                capture_repository_snapshot(temporary, state="unavailable")


if __name__ == "__main__":
    unittest.main()

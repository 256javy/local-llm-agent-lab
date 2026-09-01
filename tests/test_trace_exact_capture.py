from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile
import unittest

from llm_lab.core import LabError
from llm_lab.traces import TraceStore, begin_exact_capture, finish_exact_capture


def git(repo: pathlib.Path, *arguments: str) -> None:
    subprocess.run(["git", "-C", str(repo), *arguments], check=True, capture_output=True, text=True)


class ExactCaptureTests(unittest.TestCase):
    def make_repo(self, root: pathlib.Path) -> pathlib.Path:
        repo = root / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "Fixture")
        git(repo, "config", "user.email", "fixture@example.test")
        (repo / "tracked.txt").write_text("inicio\n", encoding="utf-8")
        git(repo, "add", "tracked.txt")
        git(repo, "commit", "-qm", "fixture")
        return repo

    def test_begin_and_finish_publish_initial_final_context_and_remove_active_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            repo = self.make_repo(root)
            store = TraceStore(root / "store")
            started = begin_exact_capture(store, client="pi", repository=repo, trace_id="trace-exact")
            active = pathlib.Path(started["activePath"])
            self.assertEqual(active.stat().st_mode & 0o777, 0o600)
            (repo / "tracked.txt").write_text("final\n", encoding="utf-8")

            destination = finish_exact_capture(store, "trace-exact")

            self.assertFalse(active.exists())
            manifest = store.show_trace("trace-exact")["manifest"]
            self.assertEqual(manifest["captureMode"], "exact")
            initial = json.loads((destination / "repository/initial/snapshot.json").read_text(encoding="utf-8"))
            final = json.loads((destination / "repository/final/snapshot.json").read_text(encoding="utf-8"))
            self.assertTrue(initial["status"]["summary"]["clean"])
            self.assertTrue(final["status"]["summary"]["unstaged"])
            context = json.loads((destination / "effective-context/context.json").read_text(encoding="utf-8"))
            self.assertTrue(any(entry["status"] == "unknown" for entry in context["entries"]))

    def test_untracked_content_is_opt_in_limited_and_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            repo = self.make_repo(root)
            (repo / "notes.txt").write_text("api_key=super-secret-value\n", encoding="utf-8")
            store = TraceStore(root / "store")
            begin_exact_capture(
                store,
                client="opencode",
                repository=repo,
                trace_id="trace-untracked",
                include_untracked=True,
            )
            destination = finish_exact_capture(store, "trace-untracked")
            copied = (destination / "repository/initial/untracked/notes.txt").read_text(encoding="utf-8")
            self.assertNotIn("super-secret-value", copied)
            self.assertIn("REDACTED", copied)
            report = json.loads((destination / "repository/initial/untracked-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["matches"]["key"], 1)
            self.assertIn("DLP", report["warnings"][0])

    def test_rejects_a_second_active_capture_and_unknown_finish(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            repo = self.make_repo(root)
            store = TraceStore(root / "store")
            begin_exact_capture(store, client="pi", repository=repo, trace_id="trace-one")
            with self.assertRaisesRegex(LabError, "captura abierta"):
                begin_exact_capture(store, client="pi", repository=repo, trace_id="trace-two")
            with self.assertRaisesRegex(LabError, "No existe una captura abierta"):
                finish_exact_capture(store, "trace-missing")


if __name__ == "__main__":
    unittest.main()

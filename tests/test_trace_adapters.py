from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile
import unittest

from llm_lab.core import LabError
from llm_lab.traces import TraceStore, capture_opencode, capture_pi
from llm_lab.traces.adapters import normalize_opencode_export, normalize_pi_jsonl


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "traces"


class TraceAdapterTests(unittest.TestCase):
    def test_pi_normalizes_messages_tools_changes_compaction_and_unknown(self) -> None:
        metadata, events, warnings = normalize_pi_jsonl(FIXTURES / "pi-0.84-session-v3.jsonl")
        self.assertEqual(metadata["sessionId"], "pi-session-fixture")
        self.assertEqual(metadata["formatVersion"], 3)
        types = [event["type"] for event in events]
        for expected in ("user_message", "assistant_message", "observed_reasoning", "tool_call", "tool_result", "model_change", "thinking_level_change", "compaction", "branch", "system_event"):
            self.assertIn(expected, types)
        self.assertEqual([event["sequence"] for event in events], list(range(len(events))))
        self.assertTrue(any("future_entry" in warning for warning in warnings))

    def test_pi_rejects_invalid_jsonl_with_line_number(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "invalid.jsonl"
            path.write_text('{"type":"session","version":3}\nnot-json\n', encoding="utf-8")
            with self.assertRaisesRegex(LabError, "línea 2"):
                normalize_pi_jsonl(path)

    def test_pi_capture_rejects_symlink_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            link = pathlib.Path(temporary) / "session.jsonl"
            link.symlink_to(FIXTURES / "pi-0.84-session-v3.jsonl")
            with self.assertRaisesRegex(LabError, "enlace simbólico"):
                capture_pi(TraceStore(pathlib.Path(temporary) / ".local"), str(link), runner=lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "0.84.4", ""))

    def test_opencode_normalizes_messages_parts_tools_and_unknown(self) -> None:
        metadata, events, warnings = normalize_opencode_export(FIXTURES / "opencode-1.18-export.json")
        self.assertEqual(metadata["sessionId"], "ses_fixture")
        types = [event["type"] for event in events]
        for expected in ("user_message", "assistant_message", "observed_reasoning", "tool_call", "tool_result", "system_event"):
            self.assertIn(expected, types)
        self.assertTrue(any("future-part" in warning for warning in warnings))

    def test_capture_pi_preserves_raw_and_detected_versions(self) -> None:
        def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            self.assertEqual(command, ["pi", "--version"])
            return subprocess.CompletedProcess(command, 0, "0.84.4\n", "")

        with tempfile.TemporaryDirectory() as temporary:
            store = TraceStore(pathlib.Path(temporary) / ".local")
            destination = capture_pi(store, str(FIXTURES / "pi-0.84-session-v3.jsonl"), trace_id="pi-fixture", runner=runner)
            manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["source"]["version"], "0.84.4")
            self.assertEqual(manifest["source"]["formatVersion"], 3)
            self.assertTrue((destination / "raw" / "session.jsonl").is_file())

    def test_capture_opencode_lists_before_export_and_rejects_missing_session(self) -> None:
        export = (FIXTURES / "opencode-1.18-export.json").read_text(encoding="utf-8")
        calls: list[list[str]] = []

        def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            if command == ["opencode", "--version"]:
                return subprocess.CompletedProcess(command, 0, "1.18.25\n", "")
            if command == ["opencode", "session", "list", "--help"]:
                return subprocess.CompletedProcess(command, 0, "--format table|json\n", "")
            if command == ["opencode", "export", "--help"]:
                return subprocess.CompletedProcess(command, 0, "export [sessionID] --sanitize\n", "")
            if command == ["opencode", "session", "list", "--format", "json"]:
                return subprocess.CompletedProcess(command, 0, '[{"id":"ses_fixture"}]\n', "")
            if command == ["opencode", "export", "ses_fixture"]:
                return subprocess.CompletedProcess(command, 0, export, "")
            raise AssertionError(command)

        with tempfile.TemporaryDirectory() as temporary:
            store = TraceStore(pathlib.Path(temporary) / ".local")
            destination = capture_opencode(store, "ses_fixture", trace_id="opencode-fixture", runner=runner)
            self.assertTrue((destination / "raw" / "export.json").is_file())
            self.assertEqual(calls[-2:], [["opencode", "session", "list", "--format", "json"], ["opencode", "export", "ses_fixture"]])
            manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["source"]["capabilities"]["sanitize"])

            with self.assertRaisesRegex(LabError, "no encontrada"):
                capture_opencode(store, "missing", runner=runner)
            self.assertNotIn(["opencode", "export", "missing"], calls)


if __name__ == "__main__":
    unittest.main()

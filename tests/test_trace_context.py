from __future__ import annotations

import pathlib
import tempfile
import unittest

from llm_lab.core import LabError
from llm_lab.traces.context import collect_effective_context, confirmed_loaded_context, discover_effective_context


class EffectiveContextTests(unittest.TestCase):
    def test_discovers_root_and_nested_rules_without_reading_their_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / "AGENTS.md").write_text("TOKEN=should-not-be-read", encoding="utf-8")
            nested = root / "package"
            nested.mkdir()
            (nested / "AGENTS.md").write_text("SECRET=should-not-be-read", encoding="utf-8")

            entries = discover_effective_context(root)

            rules = [entry for entry in entries if entry["kind"] == "rule"]
            self.assertEqual([entry["status"] for entry in rules], ["discovered", "discovered"])
            self.assertEqual([entry["evidence"]["path"] for entry in rules], ["AGENTS.md", "package/AGENTS.md"])
            self.assertNotIn("TOKEN", str(entries))
            self.assertNotIn("SECRET", str(entries))

    def test_discovers_only_relevant_requested_client_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / "opencode.json").write_text('{"apiKey":"not emitted"}', encoding="utf-8")
            (root / "pi.json").write_text('{"token":"not emitted"}', encoding="utf-8")

            entries = discover_effective_context(root, client="opencode")

            configs = [entry for entry in entries if entry["kind"] == "client_config"]
            self.assertEqual(len(configs), 1)
            self.assertEqual(configs[0]["name"], "opencode_config")
            self.assertEqual(configs[0]["status"], "discovered")
            self.assertNotIn("not emitted", str(entries))

    def test_explicit_evidence_confirms_only_observed_fields(self) -> None:
        snapshot = collect_effective_context(
            pathlib.Path.cwd(),
            client="pi",
            confirmations={
                "model": {"value": "local/model", "evidence": {"eventId": "model-change-3"}},
                "tools": {"value": [{"name": "read"}], "evidence": {"requestId": "req-7"}},
            },
        )

        fields = {entry["kind"]: entry for entry in snapshot["entries"] if entry["kind"] in {"model", "profile", "runtime", "system_prompt", "developer_prompt", "tools"}}
        self.assertEqual(snapshot["schemaVersion"], 1)
        self.assertEqual(fields["model"]["status"], "confirmed_loaded")
        self.assertEqual(fields["model"]["evidence"]["source"]["eventId"], "model-change-3")
        self.assertEqual(fields["tools"]["status"], "confirmed_loaded")
        for field in ("profile", "runtime", "system_prompt", "developer_prompt"):
            self.assertEqual(fields[field]["status"], "unknown")
            self.assertEqual(fields[field]["evidence"]["kind"], "unavailable")

    def test_confirmation_requires_evidence_and_redacts_secret_values(self) -> None:
        with self.assertRaisesRegex(LabError, "evidence explícita"):
            confirmed_loaded_context({"model": {"value": "local/model"}})

        entries, redactions = confirmed_loaded_context({
            "system_prompt": {
                "value": "Authorization: Bearer private-value",
                "evidence": {"eventId": "system-1", "apiKey": "not-retained"},
            }
        })
        self.assertEqual(entries["system_prompt"]["value"], "[REDACTED]")
        self.assertNotIn("apiKey", entries["system_prompt"]["evidence"]["source"])
        self.assertTrue(redactions)
        self.assertNotIn("private-value", str(entries))
        self.assertNotIn("not-retained", str(entries))

        entries, _ = confirmed_loaded_context({
            "developer_prompt": {"value": "api_key=another-private-value", "evidence": {"eventId": "developer-1"}}
        })
        self.assertEqual(entries["developer_prompt"]["value"], "[REDACTED]")
        self.assertNotIn("another-private-value", str(entries))

    def test_rejects_unknown_client_and_confirmation_field(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(LabError, "Cliente"):
                discover_effective_context(pathlib.Path(temporary), client="other")
        with self.assertRaisesRegex(LabError, "no confirmable"):
            confirmed_loaded_context({"rules": {"value": "x", "evidence": {"eventId": "1"}}})


if __name__ == "__main__":
    unittest.main()

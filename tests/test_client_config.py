from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile
import unittest

from llm_lab.cli import merge_settings, pi_config_drift, pi_model
from llm_lab.core import load_profiles, validate_profile


ROOT = pathlib.Path(__file__).resolve().parents[1]
CLI = ROOT / "bin/llm-lab"


def invoke(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["LLM_LAB_DATA_DIR"] = "/tmp/local-llm-agent-lab-tests"
    environment["LLM_LAB_DATA_MOUNT"] = ""
    return subprocess.run([str(CLI), *arguments], cwd=ROOT, env=environment, text=True, capture_output=True)


class PiClientConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profiles = load_profiles(ROOT)

    def test_reasoning_models_send_thinking_budget_and_toggle(self) -> None:
        for profile in self.profiles.values():
            model = pi_model(profile)
            self.assertLessEqual(model["contextWindow"], profile["server"]["contextSize"])
            self.assertLessEqual(model["maxTokens"], profile["server"]["contextSize"] // 4)
            if profile["capabilities"]["reasoning"] is True:
                self.assertEqual(model["compat"]["thinkingTokenBudgetField"], "thinking_budget_tokens")
                self.assertEqual(model["compat"]["thinkingFormat"], "chat-template")
                self.assertEqual(model["compat"]["chatTemplateKwargs"], {"enable_thinking": {"$var": "thinking.enabled"}})

    def test_generated_config_has_no_drift(self) -> None:
        result = invoke("client-config", "pi")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(pi_config_drift(json.loads(result.stdout), self.profiles), [])

    def test_drift_detects_context_mismatch_and_missing_budget(self) -> None:
        profile = self.profiles["qwen-3.8-27b-iq3xxs-mtp"]
        config = {"providers": {"local-lab": {"compat": {}, "models": [
            {"id": profile["id"], "contextWindow": 98304, "maxTokens": 24576},
            {"id": "not-a-profile", "contextWindow": 999999},
        ]}}}
        issues = pi_config_drift(config, self.profiles)
        self.assertEqual(len(issues), 3)
        self.assertTrue(any("contextWindow 98304" in issue for issue in issues))
        self.assertTrue(any("thinkingTokenBudgetField" in issue for issue in issues))

    def test_pi_settings_reserve_covers_largest_output(self) -> None:
        result = invoke("client-config", "pi-settings")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        largest_output = max(pi_model(profile)["maxTokens"] for profile in self.profiles.values())
        self.assertGreaterEqual(payload["compaction"]["reserveTokens"], largest_output)
        self.assertEqual(payload["defaultThinkingLevel"], "medium")
        self.assertLess(payload["thinkingBudgets"]["high"], min(p["server"]["contextSize"] for p in self.profiles.values()) // 4)

    def test_pi_settings_merge_preserves_user_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = pathlib.Path(directory) / "settings.json"
            destination.write_text(json.dumps({"theme": "dark", "defaultThinkingLevel": "high", "compaction": {"enabled": False, "custom": 1}}), encoding="utf-8")
            result = invoke("client-config", "pi-settings", "--output", str(destination), "--force")
            self.assertEqual(result.returncode, 0, result.stderr)
            merged = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(merged["theme"], "dark")
            self.assertEqual(merged["defaultThinkingLevel"], "medium")
            self.assertTrue(merged["compaction"]["enabled"])
            self.assertEqual(merged["compaction"]["custom"], 1)
            self.assertEqual(len(list(pathlib.Path(directory).glob("settings.json.bak-*"))), 1)

    def test_merge_settings_replaces_scalars_and_merges_dicts(self) -> None:
        self.assertEqual(merge_settings({"a": 1, "b": {"x": 1}}, {"a": 2, "b": {"y": 2}}), {"a": 2, "b": {"x": 1, "y": 2}})

    def test_invalid_chat_template_is_rejected(self) -> None:
        profile = dict(self.profiles["qwen-3.6-moe-2bit"])
        profile["chatTemplate"] = {"thinkingToggleKwarg": ""}
        self.assertTrue(any("chatTemplate" in error for error in validate_profile(profile)))
        profile["chatTemplate"] = {"unknown": "x"}
        self.assertTrue(any("chatTemplate" in error for error in validate_profile(profile)))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
CLI = ROOT / "bin/llm-lab"


def invoke(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["LLM_LAB_DATA_DIR"] = "/tmp/local-llm-agent-lab-tests"
    return subprocess.run([str(CLI), *arguments], cwd=ROOT, env=environment, text=True, capture_output=True)


class CliTests(unittest.TestCase):
    def test_profiles_json(self) -> None:
        result = invoke("profiles", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(len(payload), 4)

    def test_effective_config(self) -> None:
        result = invoke("config", "show", "--effective")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["port"], 18080)
        self.assertEqual(payload["host"], "127.0.0.1")
        self.assertFalse(payload["apiKeyConfigured"])

    def test_client_configs_use_high_port(self) -> None:
        for client in ("pi", "opencode"):
            result = invoke("client-config", client)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("127.0.0.1:18080", result.stdout)

    def test_unknown_profile_has_exit_code_two(self) -> None:
        result = invoke("start", "missing-profile")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Perfil desconocido", result.stderr)

    def test_storage_report_json(self) -> None:
        result = invoke("storage", "report", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("totalBytes", payload)


if __name__ == "__main__":
    unittest.main()

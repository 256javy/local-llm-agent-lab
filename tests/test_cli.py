from __future__ import annotations

import json
import os
import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
CLI = ROOT / "bin/llm-lab"


def invoke(*arguments: str, environment_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["LLM_LAB_DATA_DIR"] = "/tmp/local-llm-agent-lab-tests"
    environment.pop("LLM_LAB_ARCHIVE_DIR", None)
    environment.update(environment_overrides or {})
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

    def test_benchmark_help_lists_extended_suites(self) -> None:
        result = invoke("benchmark", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for suite in ("quality", "tools", "context", "soak"):
            self.assertIn(suite, result.stdout)

    def test_storage_report_json(self) -> None:
        result = invoke("storage", "report", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("totalBytes", payload)
        self.assertIn("archivedModels", payload)

    def test_storage_archive_and_restore(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            data = root / "active"
            archive = root / "archive"
            model = data / "models" / "gemma-4-12b-qat-mtp"
            model.mkdir(parents=True)
            (model / "fixture.gguf").write_text("fixture", encoding="utf-8")
            environment = {"LLM_LAB_DATA_DIR": str(data), "LLM_LAB_ARCHIVE_DIR": str(archive)}
            archived = invoke("storage", "archive", "gemma-4-12b-qat-mtp", environment_overrides=environment)
            self.assertEqual(archived.returncode, 0, archived.stderr)
            self.assertFalse(model.exists())
            self.assertTrue((archive / "models" / "gemma-4-12b-qat-mtp" / "fixture.gguf").exists())
            restored = invoke("storage", "restore", "gemma-4-12b-qat-mtp", environment_overrides=environment)
            self.assertEqual(restored.returncode, 0, restored.stderr)
            self.assertTrue((model / "fixture.gguf").exists())

    def test_storage_archive_rejects_active_state_without_moving_model(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            data = root / "active"
            archive = root / "archive"
            state = root / "state"
            model = data / "models" / "gemma-4-12b-qat-mtp"
            model.mkdir(parents=True)
            (model / "fixture.gguf").write_text("fixture", encoding="utf-8")
            state_dir = state / "local-llm-agent-lab"
            state_dir.mkdir(parents=True)
            (state_dir / "state.json").write_text('{"state":"healthy"}\n', encoding="utf-8")
            environment = {
                "LLM_LAB_DATA_DIR": str(data),
                "LLM_LAB_ARCHIVE_DIR": str(archive),
                "XDG_STATE_HOME": str(state),
            }
            result = invoke("storage", "archive", "gemma-4-12b-qat-mtp", environment_overrides=environment)
            self.assertEqual(result.returncode, 1)
            self.assertIn("Detén el perfil activo", result.stderr)
            self.assertTrue((model / "fixture.gguf").exists())
            self.assertFalse((archive / "models" / "gemma-4-12b-qat-mtp").exists())


if __name__ == "__main__":
    unittest.main()

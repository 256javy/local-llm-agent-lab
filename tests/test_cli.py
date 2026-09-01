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
        self.assertEqual(len(payload), 5)

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

    def test_native_bench_help_exposes_reproducibility_controls(self) -> None:
        result = invoke("bench", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for option in ("--matrix", "--output", "--repetitions", "--no-warmup"):
            self.assertIn(option, result.stdout)

    def test_trace_help_exposes_capture_list_and_show(self) -> None:
        result = invoke("trace", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for action in ("capture", "begin", "finish", "list", "show"):
            self.assertIn(action, result.stdout)

    def test_trace_begin_and_finish_json(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Fixture"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "fixture@example.test"], check=True)
            (repo / "fixture.txt").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "fixture.txt"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
            store = root / "store"
            begun = invoke(
                "trace", "--store", str(store), "begin", "--client", "pi",
                "--repo", str(repo), "--trace-id", "trace-cli-exact", "--json",
            )
            self.assertEqual(begun.returncode, 0, begun.stderr)
            self.assertEqual(json.loads(begun.stdout)["traceId"], "trace-cli-exact")
            finished = invoke("trace", "--store", str(store), "finish", "trace-cli-exact", "--json")
            self.assertEqual(finished.returncode, 0, finished.stderr)
            self.assertEqual(json.loads(finished.stdout)["captureMode"], "exact")

    def test_trace_list_and_show_json(self) -> None:
        import tempfile
        from llm_lab.traces import TraceStore

        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            raw = root / "raw.json"
            raw.write_text("{}", encoding="utf-8")
            store_path = root / ".local"
            TraceStore(store_path).create_trace(
                trace_id="trace-cli",
                source={"client": "pi", "version": "0.84.4", "captureCommand": "fixture"},
                raw_files={"raw.json": raw},
                events=[],
            )
            listed = invoke("trace", "--store", str(store_path), "list", "--json")
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertEqual(json.loads(listed.stdout)[0]["traceId"], "trace-cli")
            shown = invoke("trace", "--store", str(store_path), "show", "trace-cli", "--json")
            self.assertEqual(shown.returncode, 0, shown.stderr)
            self.assertEqual(json.loads(shown.stdout)["manifest"]["traceId"], "trace-cli")

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

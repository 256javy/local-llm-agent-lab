from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from llm_lab.core import LabError, compose_env, docker_project_running, http_json, load_profiles, load_settings, parse_env_file, port_available, validate_profile


ROOT = pathlib.Path(__file__).resolve().parents[1]


class EnvironmentTests(unittest.TestCase):
    def test_parse_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / ".env"
            path.write_text("# comment\nA=one\nB=\"two\"\nEMPTY=\n", encoding="utf-8")
            self.assertEqual(parse_env_file(path), {"A": "one", "B": "two", "EMPTY": ""})

    def test_environment_overrides_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / ".env").write_text("LLM_LAB_PORT=19000\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"LLM_LAB_PORT": "19001"}):
                settings = load_settings(root)
            self.assertEqual(settings.port, 19001)

    def test_archive_directory_is_optional_and_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.dict(os.environ, {"LLM_LAB_ARCHIVE_DIR": temporary}, clear=False):
                settings = load_settings(ROOT)
            self.assertEqual(settings.archive_dir, pathlib.Path(temporary).resolve())

    def test_cuda_architecture_override_replaces_profile_default(self) -> None:
        with mock.patch.dict(os.environ, {"LLM_LAB_CUDA_ARCHITECTURES": "89"}, clear=False):
            settings = load_settings(ROOT)
        profile = load_profiles(ROOT)["gemma-4-12b-qat-mtp"]
        arguments = compose_env(settings, profile)["LLM_LAB_RUNTIME_CMAKE_ARGS"]
        self.assertIn("-DCMAKE_CUDA_ARCHITECTURES=89", arguments)
        self.assertNotIn("-DCMAKE_CUDA_ARCHITECTURES=120", arguments)

    def test_invalid_port_fails(self) -> None:
        with mock.patch.dict(os.environ, {"LLM_LAB_PORT": "99999"}):
            with self.assertRaises(LabError) as raised:
                load_settings(ROOT)
        self.assertEqual(raised.exception.exit_code, 2)


class ProfileTests(unittest.TestCase):
    def test_repository_profiles_are_valid(self) -> None:
        profiles = load_profiles(ROOT)
        self.assertEqual(
            set(profiles),
            {
                "gemma-4-12b-qat-mtp",
                "gemma-4-26b-a4b-quality",
                "qwen-3.6-moe-2bit",
                "qwen-3.8-27b-iq3xxs-mtp",
                "qwen3-coder-30b-a3b-iq3xxs",
            },
        )

    def test_repository_profiles_pin_llama_cpp_for_sm120(self) -> None:
        profiles = load_profiles(ROOT)
        revisions = {profile["runtime"]["revision"] for profile in profiles.values()}
        self.assertEqual(revisions, {"57291f2644af8c9df0dd8d44395881c5bdcf0ecd"})
        cmake_args = {tuple(profile["runtime"]["cmakeArgs"]) for profile in profiles.values()}
        self.assertEqual(len(cmake_args), 1)
        for profile in profiles.values():
            self.assertIn("-DCMAKE_CUDA_ARCHITECTURES=120", profile["runtime"]["cmakeArgs"])

    def test_docker_runtime_uses_cuda_13(self) -> None:
        dockerfile = (ROOT / "docker/llama-cpp/Dockerfile").read_text(encoding="utf-8")
        self.assertIn("nvidia/cuda:13.0.3-devel-ubuntu24.04", dockerfile)
        self.assertIn("nvidia/cuda:13.0.3-runtime-ubuntu24.04", dockerfile)
        self.assertIn("LLAMA_USE_PREBUILT_UI=OFF", dockerfile)
        self.assertIn("--target llama-server llama-bench", dockerfile)
        self.assertIn("/usr/local/bin/llama-bench", dockerfile)
        self.assertNotIn("LLAMA_BUILD_WEBUI", dockerfile)

    def test_missing_fields_are_reported(self) -> None:
        errors = validate_profile({"id": "broken"})
        self.assertTrue(errors)
        self.assertIn("faltan campos", errors[0])

    def test_duplicate_profile_ids_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            directory = root / "config/profiles"
            directory.mkdir(parents=True)
            source = json.loads((ROOT / "config/profiles/gemma-4-12b-qat-mtp.json").read_text(encoding="utf-8"))
            (directory / "a.json").write_text(json.dumps(source), encoding="utf-8")
            (directory / "b.json").write_text(json.dumps(source), encoding="utf-8")
            with self.assertRaises(LabError):
                load_profiles(root)


class NetworkTests(unittest.TestCase):
    def test_ephemeral_loopback_port_is_available(self) -> None:
        self.assertTrue(port_available("127.0.0.1", 0))

    def test_connection_reset_is_reported_as_endpoint_unavailable(self) -> None:
        with mock.patch(
            "urllib.request.urlopen", side_effect=ConnectionResetError("reinicio durante la carga")
        ):
            with self.assertRaisesRegex(LabError, "Endpoint no disponible"):
                http_json("http://127.0.0.1:18080/health")

    @mock.patch("llm_lab.core.run")
    def test_project_container_detection_uses_compose_label(self, mocked_run: mock.Mock) -> None:
        mocked_run.return_value.returncode = 0
        mocked_run.return_value.stdout = "container-id\n"
        self.assertTrue(docker_project_running())
        command = mocked_run.call_args.args[0]
        self.assertIn("label=com.docker.compose.project=local-llm-agent-lab", command)


if __name__ == "__main__":
    unittest.main()

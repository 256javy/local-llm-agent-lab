from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

from llm_lab.core import LabError, load_profiles, load_settings
from llm_lab.native_bench import execute_native_bench, load_matrix, parse_llama_bench_json, translate_server_arguments


ROOT = pathlib.Path(__file__).resolve().parents[1]


class MatrixTests(unittest.TestCase):
    def test_standard_matrix_is_clamped_to_profile_context(self) -> None:
        _, tests = load_matrix(ROOT / "benchmarks/native-matrix.json", 9000)
        self.assertEqual([test.test_id for test in tests], ["pp512", "pp2048", "pp8192", "tg128", "tg512", "tg128-d8192"])

    def test_server_translation_excludes_sampling_and_mtp(self) -> None:
        translated, ignored = translate_server_arguments([
            "--n-gpu-layers", "99", "--flash-attn", "on", "--cache-type-k", "q8_0",
            "--mmap", "--spec-type", "draft-mtp", "--temp", "0.5", "--jinja",
        ])
        self.assertEqual(translated, ["-ngl", "99", "-fa", "on", "-ctk", "q8_0", "--load-mode", "mmap"])
        self.assertEqual(ignored, ["--spec-type", "draft-mtp", "--temp", "0.5", "--jinja"])

    def test_invalid_raw_is_rejected(self) -> None:
        with self.assertRaisesRegex(LabError, "JSON válido"):
            parse_llama_bench_json("not-json", "pp512")


class ExecutionTests(unittest.TestCase):
    def test_missing_model_points_to_pull(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = load_settings(ROOT)
            settings = settings.__class__(**{**settings.__dict__, "data_dir": pathlib.Path(temporary)})
            profile = load_profiles(ROOT)["gemma-4-12b-qat-mtp"]
            with self.assertRaisesRegex(LabError, "llm-lab pull"):
                execute_native_bench(
                    settings, profile, matrix_path=ROOT / "benchmarks/native-matrix.json",
                    output_root=pathlib.Path(temporary) / "results", repetitions=1,
                )

    def test_results_are_resumable_and_manifest_marks_mtp_unmeasured(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            settings = load_settings(ROOT)
            settings = settings.__class__(**{**settings.__dict__, "data_dir": root / "data"})
            profile = load_profiles(ROOT)["gemma-4-12b-qat-mtp"]
            model = settings.data_dir / "models" / profile["id"] / profile["model"]["file"]
            model.parent.mkdir(parents=True)
            model.write_text("fixture", encoding="utf-8")
            row = [{"avg_ts": 123.4, "stddev_ts": 1.2}]
            runner = mock.Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(row), ""))
            arguments = dict(
                matrix_path=ROOT / "benchmarks/native-matrix.json", output_root=root / "results", repetitions=1,
                runner=runner,
            )
            manifest_path = execute_native_bench(settings, profile, **arguments)
            first_count = runner.call_count
            execute_native_bench(settings, profile, **arguments)
            self.assertEqual(runner.call_count, first_count)
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertFalse(payload["mtpMeasured"])
            self.assertEqual(payload["runtimeRevision"], profile["runtime"]["revision"])
            self.assertTrue((manifest_path.parent / "summary.md").exists())


if __name__ == "__main__":
    unittest.main()

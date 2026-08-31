from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

from llm_lab.core import LabError, load_profiles, load_settings
from llm_lab.mtp_sweep import execute_mtp_sweep, profile_variant, recommend_case, summarize_benchmark


ROOT = pathlib.Path(__file__).resolve().parents[1]


class MtpSweepTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = load_profiles(ROOT)["gemma-4-12b-qat-mtp"]

    def test_profile_variant_removes_all_speculation_for_off_case(self) -> None:
        variant = profile_variant(self.profile, mtp_enabled=False)
        self.assertNotIn("draftModel", variant)
        self.assertNotIn("--spec-type", variant["server"]["arguments"])
        self.assertNotIn("--spec-draft-n-max", variant["server"]["arguments"])
        self.assertIn("--spec-type", self.profile["server"]["arguments"])

    def test_profile_variant_requires_declared_mtp_and_positive_limit(self) -> None:
        with self.assertRaisesRegex(LabError, "positivo"):
            profile_variant(self.profile, mtp_enabled=True, draft_n_max=0)
        no_mtp = json.loads(json.dumps(self.profile))
        no_mtp["server"]["arguments"] = ["--jinja"]
        with self.assertRaisesRegex(LabError, "no declara MTP"):
            profile_variant(no_mtp, mtp_enabled=True, draft_n_max=2)

    def test_summary_reports_latency_and_acceptance_from_server_timings(self) -> None:
        payload = {
            "passed": True,
            "records": [{
                "durationsSeconds": [0.2, 0.4],
                "responses": [
                    {"timings": {"draft_n": 8, "draft_n_accepted": 6}},
                    {"timings": {"draft_n": 2, "draft_n_accepted": 2}},
                ],
            }],
        }
        summary = summarize_benchmark(payload)
        self.assertEqual(summary["latencyMedianSeconds"], 0.30000000000000004)
        self.assertEqual(summary["draftTokens"], 10)
        self.assertEqual(summary["acceptedDraftTokens"], 8)
        self.assertEqual(summary["draftAcceptanceRate"], 0.8)

    def test_recommendation_requires_quality_and_observed_acceptance_for_mtp(self) -> None:
        cases = [
            {"eligible": True, "latencyMedianSeconds": 0.4, "draftAcceptanceRate": None, "draftNMax": None, "mtpEnabled": False},
            {"eligible": False, "latencyMedianSeconds": 0.1, "draftAcceptanceRate": None, "draftNMax": 2, "mtpEnabled": True},
            {"eligible": True, "latencyMedianSeconds": 0.2, "draftAcceptanceRate": 0.75, "draftNMax": 4, "mtpEnabled": True},
        ]
        self.assertEqual(recommend_case(cases)["draftNMax"], 4)

    def test_execute_sweeps_off_then_each_limit_and_stops_every_case(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            settings = load_settings(ROOT)
            settings = settings.__class__(**{**settings.__dict__, "data_dir": root / "data"})
            started: list[dict] = []
            stopped: list[dict] = []
            result_number = 0

            def fake_start(_settings, variant, *, build_only=False, build=True) -> None:
                self.assertFalse(build_only)
                self.assertFalse(build)
                started.append(variant)

            def fake_stop(_settings, variant) -> None:
                stopped.append(variant)

            def fake_runner(command, **_kwargs):
                nonlocal result_number
                result_number += 1
                profile_file = pathlib.Path(command[command.index("--profile-file") + 1])
                profile = json.loads(profile_file.read_text(encoding="utf-8"))
                arguments = profile["server"]["arguments"]
                mtp = "--spec-type" in arguments
                limit = int(arguments[arguments.index("--spec-draft-n-max") + 1]) if mtp else 0
                destination = root / f"result-{result_number}.json"
                destination.write_text(json.dumps({
                    "passed": True,
                    "records": [{
                        "durationsSeconds": [0.5 - limit / 100],
                        "responses": [{"timings": {"draft_n": limit, "draft_n_accepted": limit - 1}}] if mtp else [{}],
                    }],
                }), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, f"{destination}\n", "")

            environment = {"XDG_STATE_HOME": str(root / "state")}
            with mock.patch.dict(os.environ, environment, clear=False), \
                 mock.patch("llm_lab.mtp_sweep.docker_project_running", return_value=False), \
                 mock.patch("llm_lab.mtp_sweep.docker_container_running", return_value=False):
                manifest = execute_mtp_sweep(
                    settings,
                    self.profile,
                    draft_n_max=[4, 2],
                    suites=["quality", "tools"],
                    repetitions=1,
                    output_root=root / "output",
                    start_profile=fake_start,
                    stop_managed=fake_stop,
                    command_runner=fake_runner,
                )
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual([case["draftNMax"] for case in payload["cases"]], [None, 2, 4])
            self.assertEqual(len(started), 3)
            self.assertEqual(len(stopped), 3)
            self.assertNotIn("draftModel", started[0])
            self.assertTrue(started[1]["server"]["arguments"][-4:] == ["--spec-type", "draft-mtp", "--spec-draft-n-max", "2"])
            self.assertEqual(payload["recommended"], {"mtpEnabled": True, "draftNMax": 4})


if __name__ == "__main__":
    unittest.main()

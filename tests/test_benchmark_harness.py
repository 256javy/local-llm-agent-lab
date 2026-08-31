from __future__ import annotations

import importlib.util
import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("benchmark_harness", ROOT / "benchmarks" / "run.py")
assert SPEC is not None and SPEC.loader is not None
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)


class ContextFixturesTests(unittest.TestCase):
    def test_long_context_fixtures_have_distinct_16k_and_32k_contracts(self) -> None:
        expected = {
            "retrieval-16k.json": ("context-retrieval-16k", 15000, "MANDUARÁ-16042"),
            "retrieval-32k.json": ("context-retrieval-32k", 30000, "MANDUARÁ-32084"),
        }
        for filename, (fixture_id, repetitions, answer) in expected.items():
            fixture = json.loads((ROOT / "benchmarks" / "prompts" / "context" / filename).read_text(encoding="utf-8"))
            self.assertEqual(fixture["id"], fixture_id)
            self.assertEqual(fixture["contextPadding"]["repetitions"], repetitions)
            self.assertEqual(fixture["assert"]["contentEquals"], answer)


class SoakDegradationTests(unittest.TestCase):
    def test_detects_latency_vram_growth_and_response_failures(self) -> None:
        report = HARNESS.soak_degradation(
            [{"fixture": "smoke", "passed": False, "durationsSeconds": [1.0] * 5 + [2.0] * 5}],
            [{"usedMiB": 1000}, {"usedMiB": 1600}],
            latency_factor=1.5,
            vram_growth_mib=512,
        )
        self.assertTrue(report["detected"])
        self.assertEqual(report["responseFailureFixtures"], ["smoke"])
        self.assertTrue(report["latency"][0]["degraded"])
        self.assertEqual(report["vram"]["growthMiB"], 600)
        self.assertTrue(report["vram"]["degraded"])

    def test_short_diagnostic_run_has_no_latency_comparison(self) -> None:
        report = HARNESS.soak_degradation(
            [{"fixture": "smoke", "passed": True, "durationsSeconds": [1.0, 4.0, 4.0, 4.0, 4.0]}],
            [],
            latency_factor=1.5,
            vram_growth_mib=512,
        )
        self.assertFalse(report["detected"])
        self.assertEqual(report["latency"], [])
        self.assertFalse(report["vram"]["available"])

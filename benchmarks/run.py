#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import platform
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request


def post(url: str, payload: dict) -> tuple[dict, float]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=600) as response:
        result = json.loads(response.read().decode("utf-8"))
    return result, time.perf_counter() - started


def gpu_snapshot() -> dict | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.used,memory.total", "--format=csv,noheader,nounits"],
            check=True, capture_output=True, text=True,
        )
        name, driver, used, total = [item.strip() for item in result.stdout.splitlines()[0].split(",")]
        return {"name": name, "driver": driver, "usedMiB": int(used), "totalMiB": int(total)}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


class VramSampler:
    def __init__(self, interval_seconds: float) -> None:
        self.interval_seconds = interval_seconds
        self.samples: list[dict] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> None:
        snapshot = gpu_snapshot()
        if snapshot is None:
            return
        with self._lock:
            self.samples.append({"timestamp": time.time(), **snapshot})

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            self._sample()

    def start(self) -> None:
        self._sample()
        self._thread = threading.Thread(target=self._run, name="llm-lab-vram-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> list[dict]:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
        self._sample()
        with self._lock:
            return list(self.samples)


def image_metadata(profile: str) -> dict | None:
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", f"local/local-llm-agent-lab:{profile}", "--format", "{{json .}}"],
            check=True, capture_output=True, text=True,
        )
        image = json.loads(result.stdout)
        environment = dict(item.split("=", 1) for item in image.get("Config", {}).get("Env", []) if "=" in item)
        return {"id": image.get("Id"), "created": image.get("Created"), "cudaVersion": environment.get("CUDA_VERSION")}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        return None


def response_matches(response: dict, expectation: dict) -> bool:
    message = response.get("choices", [{}])[0].get("message", {})
    if "contentContains" in expectation and expectation["contentContains"] not in (message.get("content") or ""):
        return False
    if "toolName" in expectation:
        calls = message.get("tool_calls") or []
        matching = [call for call in calls if call.get("function", {}).get("name") == expectation["toolName"]]
        if not matching:
            return False
        try:
            arguments = json.loads(matching[0]["function"]["arguments"])
        except (KeyError, TypeError, json.JSONDecodeError):
            return False
        if arguments != expectation.get("arguments", arguments):
            return False
    if expectation.get("noToolCall") and message.get("tool_calls"):
        return False
    if "contentEquals" in expectation and (message.get("content") or "").strip() != expectation["contentEquals"]:
        return False
    return True


def expand_fixture(fixture: dict) -> dict:
    padding = fixture.pop("contextPadding", None)
    if not padding:
        return fixture
    token, repetitions = padding["token"], int(padding["repetitions"])
    for message in fixture["messages"]:
        message["content"] = message["content"].replace("{{CONTEXT_PADDING}}", (token + " ") * repetitions)
    return fixture


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * fraction))]


def soak_degradation(
    records: list[dict],
    vram_samples: list[dict],
    latency_factor: float,
    vram_growth_mib: int,
) -> dict:
    latency = []
    response_failures = [record["fixture"] for record in records if not record["passed"]]
    for record in records:
        durations = record["durationsSeconds"]
        window_size = len(durations) // 5
        if window_size < 2:
            continue
        initial = statistics.median(durations[:window_size])
        final = statistics.median(durations[-window_size:])
        ratio = final / initial if initial else None
        latency.append({
            "fixture": record["fixture"],
            "samplesPerWindow": window_size,
            "initialMedianSeconds": initial,
            "finalMedianSeconds": final,
            "ratio": ratio,
            "degraded": ratio is not None and ratio >= latency_factor,
        })

    vram = {"available": bool(vram_samples), "degraded": False}
    if vram_samples:
        initial_used = vram_samples[0]["usedMiB"]
        peak_used = max(sample["usedMiB"] for sample in vram_samples)
        growth = peak_used - initial_used
        vram.update({
            "initialUsedMiB": initial_used,
            "peakUsedMiB": peak_used,
            "growthMiB": growth,
            "degraded": growth >= vram_growth_mib,
        })

    detected = bool(response_failures) or any(item["degraded"] for item in latency) or vram["degraded"]
    return {
        "detected": detected,
        "criteria": {
            "latencyFactor": latency_factor,
            "vramGrowthMiB": vram_growth_mib,
            "minimumRepetitionsForLatency": 10,
        },
        "responseFailureFixtures": response_failures,
        "latency": latency,
        "vram": vram,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--suite", choices=["smoke", "performance", "agent", "quality", "tools", "context", "soak"], default="smoke")
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--vram-sample-interval", type=float, default=5.0)
    parser.add_argument("--degradation-latency-factor", type=float, default=1.5)
    parser.add_argument("--degradation-vram-growth-mib", type=int, default=512)
    parser.add_argument("--profile-file", type=pathlib.Path, required=True)
    args = parser.parse_args()
    if args.vram_sample_interval <= 0:
        parser.error("--vram-sample-interval debe ser mayor que cero")
    if args.degradation_latency_factor <= 1:
        parser.error("--degradation-latency-factor debe ser mayor que uno")
    if args.degradation_vram_growth_mib < 0:
        parser.error("--degradation-vram-growth-mib no puede ser negativo")
    root = pathlib.Path(__file__).resolve().parent
    fixtures_by_suite = {
        "smoke": [root / "prompts/smoke.json", root / "prompts/tool.json"],
        "agent": [root / "prompts/tool.json"],
        "performance": [root / "prompts/performance.json"],
        "quality": sorted((root / "prompts/quality").glob("*.json")),
        "tools": sorted((root / "prompts/tools").glob("*.json")),
        "context": sorted((root / "prompts/context").glob("*.json")),
        "soak": [root / "prompts/smoke.json", root / "prompts/tool.json"],
    }
    fixtures = fixtures_by_suite[args.suite]
    repetitions = args.repetitions or (50 if args.suite == "soak" else 3)
    records = []
    all_passed = True
    sampler = VramSampler(args.vram_sample_interval)
    sampler.start()
    try:
        for fixture_path in fixtures:
            fixture = expand_fixture(json.loads(fixture_path.read_text(encoding="utf-8")))
            fixture_id = fixture.pop("id")
            expectation = fixture.pop("assert", {})
            durations = []
            responses = []
            for _ in range(repetitions):
                response, duration = post(f"{args.endpoint}/chat/completions", {"model": args.profile, **fixture})
                durations.append(duration)
                responses.append(response)
            passed = all(response_matches(response, expectation) for response in responses)
            all_passed = all_passed and passed
            records.append({"fixture": fixture_id, "passed": passed, "durationsSeconds": durations, "medianSeconds": statistics.median(durations), "p95Seconds": percentile(durations, 0.95), "responses": responses})
    finally:
        vram_samples = sampler.stop()
    degradation = None
    if args.suite == "soak":
        degradation = soak_degradation(
            records, vram_samples, args.degradation_latency_factor, args.degradation_vram_growth_mib,
        )
        all_passed = all_passed and not degradation["detected"]
    profile = json.loads(args.profile_file.read_text(encoding="utf-8"))
    output = {
        "schemaVersion": 1,
        "timestamp": time.time(),
        "profile": args.profile,
        "suite": args.suite,
        "endpoint": args.endpoint,
        "passed": all_passed,
        "runtime": profile["runtime"],
        "model": profile["model"],
        "draftModel": profile.get("draftModel"),
        "server": profile["server"],
        "execution": {
            "repetitions": repetitions,
            "temperatureControlled": True,
            "vramSampleIntervalSeconds": args.vram_sample_interval,
        },
        "image": image_metadata(args.profile),
        "host": {"platform": platform.platform(), "python": platform.python_version(), "gpu": gpu_snapshot()},
        "vramSamples": vram_samples,
        "records": records,
    }
    if degradation is not None:
        output["degradation"] = degradation
    destination = pathlib.Path("benchmark-results") / f"{int(output['timestamp'])}-{args.profile}-{args.suite}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(destination)
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import platform
import statistics
import subprocess
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--suite", choices=["smoke", "performance", "agent", "quality", "tools", "context", "soak"], default="smoke")
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--profile-file", type=pathlib.Path, required=True)
    args = parser.parse_args()
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
        "execution": {"repetitions": repetitions, "temperatureControlled": True},
        "image": image_metadata(args.profile),
        "host": {"platform": platform.platform(), "python": platform.python_version(), "gpu": gpu_snapshot()},
        "records": records,
    }
    destination = pathlib.Path("benchmark-results") / f"{int(output['timestamp'])}-{args.profile}-{args.suite}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(destination)
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

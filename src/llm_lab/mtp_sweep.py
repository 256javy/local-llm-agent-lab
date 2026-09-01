from __future__ import annotations

import copy
import json
import pathlib
import statistics
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from typing import Any

from .core import LabError, Settings, control_lock, docker_container_running, docker_project_running, run


SUPPORTED_SUITES = frozenset({"smoke", "performance", "agent", "quality", "tools", "context", "soak"})


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * fraction))]


def _without_options(arguments: Iterable[str], names: set[str]) -> list[str]:
    result: list[str] = []
    iterator = iter(arguments)
    for argument in iterator:
        if argument in names:
            next(iterator, None)
            continue
        result.append(argument)
    return result


def profile_variant(profile: dict[str, Any], *, mtp_enabled: bool, draft_n_max: int | None = None) -> dict[str, Any]:
    """Return an in-memory server profile without changing the declarative profile."""
    if mtp_enabled and (draft_n_max is None or draft_n_max < 1):
        raise LabError("--draft-n-max debe contener enteros positivos", 2)
    arguments = profile.get("server", {}).get("arguments", [])
    has_mtp = any(
        arguments[index:index + 2] == ["--spec-type", "draft-mtp"]
        for index in range(max(0, len(arguments) - 1))
    )
    if mtp_enabled and not has_mtp:
        raise LabError(f"El perfil {profile.get('id', 'desconocido')} no declara MTP draft-mtp", 2)

    variant = copy.deepcopy(profile)
    server_arguments = _without_options(arguments, {"--spec-type", "--spec-draft-n-max"})
    if mtp_enabled:
        server_arguments.extend(["--spec-type", "draft-mtp", "--spec-draft-n-max", str(draft_n_max)])
    else:
        # Gemma uses a separate draft GGUF. Without it the off case is a real
        # non-speculative baseline; embedded-Qwen MTP is disabled by omitting
        # its speculative server flag.
        variant.pop("draftModel", None)
    variant["server"]["arguments"] = server_arguments
    return variant


def summarize_benchmark(payload: dict[str, Any]) -> dict[str, Any]:
    durations: list[float] = []
    draft_total = 0
    draft_accepted = 0
    observed_drafts = False
    for record in payload.get("records", []):
        durations.extend(value for value in record.get("durationsSeconds", []) if isinstance(value, (int, float)))
        for response in record.get("responses", []):
            timings = response.get("timings") if isinstance(response, dict) else None
            if not isinstance(timings, dict):
                continue
            drafted = timings.get("draft_n")
            accepted = timings.get("draft_n_accepted")
            if isinstance(drafted, (int, float)) and isinstance(accepted, (int, float)):
                observed_drafts = True
                draft_total += int(drafted)
                draft_accepted += int(accepted)
    return {
        "passed": bool(payload.get("passed")),
        "requests": len(durations),
        "latencyMedianSeconds": statistics.median(durations) if durations else None,
        "latencyP95Seconds": percentile(durations, 0.95) if durations else None,
        "draftTokens": draft_total if observed_drafts else None,
        "acceptedDraftTokens": draft_accepted if observed_drafts else None,
        "draftAcceptanceRate": (draft_accepted / draft_total) if draft_total else None,
    }


def summarize_case(*, mtp_enabled: bool, draft_n_max: int | None, suites: dict[str, dict[str, Any]]) -> dict[str, Any]:
    durations = [
        duration
        for suite in suites.values()
        for duration in (suite.get("_durations") or [])
        if isinstance(duration, (int, float))
    ]
    draft_total = sum(item["draftTokens"] or 0 for item in suites.values())
    accepted_total = sum(item["acceptedDraftTokens"] or 0 for item in suites.values())
    observed_drafts = any(item["draftTokens"] is not None for item in suites.values())
    passed = bool(suites) and all(item["passed"] for item in suites.values())
    acceptance = accepted_total / draft_total if draft_total else None
    # Calidad es un gate. Para MTP también debe existir una aceptación positiva;
    # de lo contrario no se puede atribuir la latencia al decoding especulativo.
    eligible = passed and (not mtp_enabled or (observed_drafts and acceptance is not None and acceptance > 0))
    compact_suites = {
        name: {key: value for key, value in item.items() if key != "_durations"}
        for name, item in suites.items()
    }
    return {
        "mtpEnabled": mtp_enabled,
        "draftNMax": draft_n_max,
        "passed": passed,
        "eligible": eligible,
        "latencyMedianSeconds": statistics.median(durations) if durations else None,
        "latencyP95Seconds": percentile(durations, 0.95) if durations else None,
        "draftTokens": draft_total if observed_drafts else None,
        "acceptedDraftTokens": accepted_total if observed_drafts else None,
        "draftAcceptanceRate": acceptance,
        "suites": compact_suites,
    }


def recommend_case(cases: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [case for case in cases if case["eligible"] and case["latencyMedianSeconds"] is not None]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda case: (
            case["latencyMedianSeconds"],
            -(case["draftAcceptanceRate"] if case["draftAcceptanceRate"] is not None else -1),
            case["draftNMax"] if case["draftNMax"] is not None else 0,
        ),
    )


def _result_path(stdout: str) -> pathlib.Path | None:
    for line in reversed(stdout.splitlines()):
        candidate = pathlib.Path(line.strip())
        if candidate.suffix == ".json" and candidate.exists():
            return candidate
    return None


def execute_mtp_sweep(
    settings: Settings,
    profile: dict[str, Any],
    *,
    draft_n_max: Iterable[int],
    suites: Iterable[str],
    repetitions: int,
    output_root: pathlib.Path,
    start_profile: Callable[..., None],
    stop_managed: Callable[..., None],
    command_runner: Callable[..., Any] = run,
) -> pathlib.Path:
    limits = sorted(set(draft_n_max))
    selected_suites = list(suites)
    if not limits or any(limit < 1 for limit in limits):
        raise LabError("--draft-n-max debe contener al menos un entero positivo", 2)
    if repetitions < 1:
        raise LabError("--repetitions debe ser mayor que cero", 2)
    invalid_suites = sorted(set(selected_suites) - SUPPORTED_SUITES)
    if not selected_suites or invalid_suites:
        detail = ", ".join(invalid_suites) if invalid_suites else "ninguna"
        raise LabError(f"Suites inválidas para el barrido: {detail}", 2)

    output_root = output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    with control_lock(settings):
        if docker_project_running() or docker_container_running() or settings.state_file.exists():
            raise LabError("Detén el perfil activo antes de barrer MTP", 1)
        with tempfile.TemporaryDirectory(prefix="llm-lab-mtp-sweep-", dir=settings.state_dir) as temporary:
            temporary_root = pathlib.Path(temporary)
            modes = [(False, None), *((True, limit) for limit in limits)]
            for index, (mtp_enabled, limit) in enumerate(modes):
                variant = profile_variant(profile, mtp_enabled=mtp_enabled, draft_n_max=limit)
                profile_file = temporary_root / f"case-{index}.json"
                profile_file.write_text(json.dumps(variant, ensure_ascii=False), encoding="utf-8")
                variant["_path"] = str(profile_file)
                suite_summaries: dict[str, dict[str, Any]] = {}
                started = False
                try:
                    # The sweep must use the already prepared image. It never
                    # triggers an implicit runtime build or model download.
                    start_profile(settings, variant, build=False)
                    started = True
                    for suite in selected_suites:
                        command = [
                            sys.executable, str(settings.repo_dir / "benchmarks" / "run.py"),
                            "--endpoint", settings.endpoint,
                            "--profile", profile["id"],
                            "--profile-file", str(profile_file),
                            "--suite", suite,
                            "--repetitions", str(repetitions),
                        ]
                        completed = command_runner(command, cwd=settings.repo_dir, check=False, capture=True)
                        result_path = _result_path(getattr(completed, "stdout", ""))
                        if result_path is None:
                            suite_summaries[suite] = {
                                "passed": False,
                                "error": (getattr(completed, "stderr", "") or "El harness no produjo JSON").strip(),
                                "_durations": [],
                            }
                            continue
                        payload = json.loads(result_path.read_text(encoding="utf-8"))
                        summary = summarize_benchmark(payload)
                        summary["result"] = str(result_path.relative_to(settings.repo_dir)) if result_path.is_relative_to(settings.repo_dir) else str(result_path)
                        summary["_durations"] = [
                            duration
                            for record in payload.get("records", [])
                            for duration in record.get("durationsSeconds", [])
                        ]
                        if getattr(completed, "returncode", 0) != 0:
                            summary["passed"] = False
                        suite_summaries[suite] = summary
                except Exception as exc:
                    suite_summaries.setdefault("startup", {"passed": False, "error": str(exc), "_durations": []})
                finally:
                    if started or docker_container_running() or settings.state_file.exists():
                        stop_managed(settings, variant)
                cases.append(summarize_case(mtp_enabled=mtp_enabled, draft_n_max=limit, suites=suite_summaries))

    recommendation = recommend_case(cases)
    payload = {
        "schemaVersion": 1,
        "timestamp": time.time(),
        "profile": profile["id"],
        "suites": selected_suites,
        "repetitions": repetitions,
        "selectionPolicy": "calidad como gate; MTP requiere aceptación observada positiva; menor latencia mediana y luego mayor aceptación",
        "cases": cases,
        "recommended": {
            "mtpEnabled": recommendation["mtpEnabled"],
            "draftNMax": recommendation["draftNMax"],
        } if recommendation else None,
    }
    destination = output_root / f"{int(payload['timestamp'])}-{profile['id']}-mtp-sweep.json"
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return destination

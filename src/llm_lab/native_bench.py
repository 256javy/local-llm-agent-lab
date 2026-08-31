from __future__ import annotations

import datetime
import json
import pathlib
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

from .core import LabError, Settings, compose_command, compose_env, file_sha256


@dataclass(frozen=True)
class NativeTest:
    test_id: str
    prompt_tokens: int
    generation_tokens: int
    depth: int


def load_matrix(path: pathlib.Path, context_size: int) -> tuple[dict[str, Any], list[NativeTest]]:
    try:
        matrix = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LabError(f"Matriz nativa inválida: {exc}", 2) from exc
    if matrix.get("schemaVersion") != 1 or not isinstance(matrix.get("tests"), list):
        raise LabError("Matriz nativa inválida: se requiere schemaVersion 1 y tests", 2)
    tests: list[NativeTest] = []
    seen: set[str] = set()
    for item in matrix["tests"]:
        try:
            test = NativeTest(
                str(item["id"]), int(item["promptTokens"]),
                int(item["generationTokens"]), int(item.get("depth", 0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LabError(f"Caso inválido en matriz nativa: {item}", 2) from exc
        if test.test_id in seen or min(test.prompt_tokens, test.generation_tokens, test.depth) < 0:
            raise LabError(f"Caso inválido o duplicado: {test.test_id}", 2)
        if test.prompt_tokens + test.generation_tokens + test.depth > context_size:
            continue
        seen.add(test.test_id)
        tests.append(test)
    if not tests:
        raise LabError(f"Ningún caso cabe en el contexto configurado ({context_size})", 2)
    return matrix, tests


def translate_server_arguments(arguments: list[str]) -> tuple[list[str], list[str]]:
    value_options = {
        "-ngl": "-ngl", "--n-gpu-layers": "-ngl",
        "-fa": "-fa", "--flash-attn": "-fa",
        "-ctk": "-ctk", "--cache-type-k": "-ctk",
        "-ctv": "-ctv", "--cache-type-v": "-ctv",
        "-sm": "-sm", "--split-mode": "-sm",
        "-mg": "-mg", "--main-gpu": "-mg",
    }
    translated: list[str] = []
    ignored: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in value_options:
            if index + 1 >= len(arguments):
                raise LabError(f"Falta valor para {argument} en el perfil", 2)
            translated.extend([value_options[argument], arguments[index + 1]])
            index += 2
        elif argument == "--mmap":
            translated.extend(["--load-mode", "mmap"])
            index += 1
        else:
            ignored.append(argument)
            if argument.startswith("-") and index + 1 < len(arguments) and not arguments[index + 1].startswith("-"):
                ignored.append(arguments[index + 1])
                index += 2
            else:
                index += 1
    return translated, ignored


def parse_llama_bench_json(raw: str, test_id: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LabError(f"llama-bench no devolvió JSON válido para {test_id}: {exc}", 1) from exc
    if not isinstance(payload, list) or not payload or not all(isinstance(item, dict) for item in payload):
        raise LabError(f"llama-bench devolvió un resultado vacío o inválido para {test_id}", 1)
    return payload


def atomic_json(path: pathlib.Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def atomic_text(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def render_summary(profile_id: str, results: list[dict[str, Any]]) -> str:
    lines = [f"# llama-bench: {profile_id}", "", "| Caso | tokens/s | desviación |", "| --- | ---: | ---: |"]
    for result in results:
        for row in result["rows"]:
            lines.append(f"| {result['id']} | {float(row['avg_ts']):.2f} | {float(row['stddev_ts']):.2f} |")
    return "\n".join(lines) + "\n"


def execute_native_bench(
    settings: Settings,
    profile: dict[str, Any],
    *,
    matrix_path: pathlib.Path,
    output_root: pathlib.Path,
    repetitions: int | None = None,
    no_warmup: bool = False,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> pathlib.Path:
    matrix, tests = load_matrix(matrix_path, profile["server"]["contextSize"])
    effective_repetitions = repetitions if repetitions is not None else int(matrix.get("repetitions", 5))
    if effective_repetitions < 1:
        raise LabError("--repetitions debe ser mayor que cero", 2)
    model_path = settings.data_dir / "models" / profile["id"] / pathlib.Path(profile["model"]["file"]).name
    if not model_path.is_file():
        raise LabError(f"Falta el GGUF de {profile['id']}; ejecuta `llm-lab pull {profile['id']}`", 1)

    translated, ignored = translate_server_arguments(profile["server"].get("arguments", []))
    run_id = f"{profile['id']}-{matrix['id']}-r{effective_repetitions}{'-no-warmup' if no_warmup else ''}"
    run_dir = output_root / run_id
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    env = compose_env(settings, profile)
    results: list[dict[str, Any]] = []
    for test in tests:
        raw_path = raw_dir / f"{test.test_id}.json"
        if raw_path.exists():
            rows = parse_llama_bench_json(raw_path.read_text(encoding="utf-8"), test.test_id)
        else:
            command = compose_command(
                settings, "run", "--rm", "--no-deps", "--entrypoint", "llama-bench", "server",
                "-m", f"/models/{profile['id']}/{model_path.name}", "-o", "json",
                "-r", str(effective_repetitions), "-p", str(test.prompt_tokens),
                "-n", str(test.generation_tokens), "-d", str(test.depth), *translated,
            )
            if no_warmup:
                command.append("--no-warmup")
            completed = runner(command, cwd=settings.repo_dir, env=env, text=True, capture_output=True)
            if completed.returncode != 0:
                detail = completed.stderr.strip() or completed.stdout.strip()
                raise LabError(f"Falló llama-bench en {test.test_id}: {detail}", 1)
            rows = parse_llama_bench_json(completed.stdout, test.test_id)
            atomic_text(raw_path, completed.stdout)
        results.append({"id": test.test_id, "rows": rows})

    manifest = {
        "schemaVersion": 1,
        "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "profile": profile["id"],
        "runtimeRevision": profile["runtime"]["revision"],
        "matrix": matrix["id"],
        "repetitions": effective_repetitions,
        "warmup": not no_warmup,
        "model": {"file": model_path.name, "sizeBytes": model_path.stat().st_size, "sha256": file_sha256(model_path)},
        "translatedArguments": translated,
        "ignoredServerArguments": ignored,
        "mtpMeasured": False,
        "tests": results,
    }
    manifest_path = run_dir / "manifest.json"
    atomic_json(manifest_path, manifest)
    atomic_text(run_dir / "summary.md", render_summary(profile["id"], results))
    return manifest_path

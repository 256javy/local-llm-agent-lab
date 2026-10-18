from __future__ import annotations

import datetime
import io
import pathlib
import re
import subprocess
import urllib.request
import zipfile
from typing import Any, Callable

from .core import LabError, Settings, compose_command, compose_env, file_sha256, require_data_mount
from .native_bench import atomic_json, translate_server_arguments

WIKITEXT_URL = "https://huggingface.co/datasets/ggml-org/ci/resolve/main/wikitext-2-raw-v1.zip"
WIKITEXT_MEMBER = "wikitext-2-raw/wiki.test.raw"

# Lines printed by llama-perplexity --kl-divergence (tools/perplexity/perplexity.cpp).
METRIC_PATTERNS = {
    "pplQ": r"Mean PPL\(Q\)\s*:\s*([\d.]+)",
    "pplBase": r"Mean PPL\(base\)\s*:\s*([\d.]+)",
    "pplRatio": r"Mean PPL\(Q\)/PPL\(base\)\s*:\s*([\d.]+)",
    "meanKld": r"Mean\s+KLD:\s*([\d.]+)",
    "medianKld": r"Median\s+KLD:\s*([\d.]+)",
    "p99Kld": r"99\.0%\s+KLD:\s*([\d.]+)",
    "maxKld": r"Maximum KLD:\s*([\d.]+)",
    "rmsDeltaPPercent": r"RMS Δp\s*:\s*([\d.]+)",
    "sameTopPPercent": r"Same top p:\s*([\d.]+)",
}


def parse_kld_output(text: str) -> dict[str, float]:
    metrics = {}
    for key, pattern in METRIC_PATTERNS.items():
        match = re.search(pattern, text)
        if match:
            metrics[key] = float(match.group(1))
    if "meanKld" not in metrics:
        raise LabError("llama-perplexity no reportó KLD; revisa la salida cruda", 1)
    return metrics


def ensure_corpus(settings: Settings, fetch: Callable[[str], bytes] | None = None) -> pathlib.Path:
    corpus = settings.data_dir / "eval" / WIKITEXT_MEMBER
    if corpus.is_file():
        return corpus
    if fetch is None:
        def fetch(url: str) -> bytes:
            with urllib.request.urlopen(url, timeout=120) as response:
                return response.read()
    with zipfile.ZipFile(io.BytesIO(fetch(WIKITEXT_URL))) as archive:
        member = next((name for name in archive.namelist() if name.endswith(WIKITEXT_MEMBER)), None)
        if member is None:
            raise LabError("El zip de wikitext-2 no contiene wiki.test.raw", 1)
        corpus.parent.mkdir(parents=True, exist_ok=True)
        corpus.write_bytes(archive.read(member))
    return corpus


def model_file(settings: Settings, profile: dict[str, Any]) -> pathlib.Path:
    path = settings.data_dir / "models" / profile["id"] / pathlib.Path(profile["model"]["file"]).name
    if not path.is_file():
        raise LabError(f"Falta el GGUF de {profile['id']}; ejecuta `llm-lab pull {profile['id']}`", 1)
    return path


def execute_kld(
    settings: Settings,
    profile: dict[str, Any],
    reference: dict[str, Any],
    *,
    output_root: pathlib.Path,
    chunks: int,
    reference_gpu_layers: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> pathlib.Path:
    if chunks < 1:
        raise LabError("--chunks debe ser mayor que cero", 2)
    require_data_mount(settings)
    corpus = ensure_corpus(settings)
    reference_path = model_file(settings, reference)
    model_path = model_file(settings, profile)
    # Logits live on the HDD next to the corpus; they are tens of GiB for large vocabularies.
    base_name = f"{reference['id']}-wikitext2-c{chunks}.kld"
    base_path = settings.data_dir / "eval" / "kld-base" / base_name
    container_base = f"/eval/kld-base/{base_name}"
    container_corpus = f"/eval/{WIKITEXT_MEMBER}"

    def perplexity(target: dict[str, Any], path: pathlib.Path, extra: list[str], gpu_layers: str | None) -> str:
        translated, _ = translate_server_arguments(target["server"].get("arguments", []))
        if gpu_layers is not None:
            translated = [*translated, "-ngl", gpu_layers]
        command = compose_command(
            settings, "run", "--rm", "--no-deps", "--entrypoint", "llama-perplexity", "server",
            "-m", f"/models/{target['id']}/{path.name}", "-f", container_corpus,
            "--chunks", str(chunks), *translated, *extra,
        )
        completed = runner(command, cwd=settings.repo_dir, env=compose_env(settings, target), text=True, capture_output=True)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[-2000:]
            raise LabError(f"Falló llama-perplexity en {target['id']}: {detail}", 1)
        return completed.stdout + completed.stderr

    if not base_path.is_file():
        base_path.parent.mkdir(parents=True, exist_ok=True)
        perplexity(reference, reference_path, ["--kl-divergence-base", container_base], reference_gpu_layers)
    output = perplexity(profile, model_path, ["--kl-divergence-base", container_base, "--kl-divergence"], None)

    result = {
        "schemaVersion": 1,
        "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "profile": profile["id"],
        "reference": reference["id"],
        "runtimeRevision": profile["runtime"]["revision"],
        "corpus": {"name": "wikitext-2-raw test", "chunks": chunks},
        "model": {"file": model_path.name, "sizeBytes": model_path.stat().st_size, "sha256": file_sha256(model_path)},
        "referenceModel": {"file": reference_path.name, "sizeBytes": reference_path.stat().st_size},
        "metrics": parse_kld_output(output),
    }
    destination = output_root / f"{int(datetime.datetime.now().timestamp())}-{profile['id']}-vs-{reference['id']}.json"
    atomic_json(destination, result)
    (destination.with_suffix(".log")).write_text(output, encoding="utf-8")
    return destination

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import pathlib
import urllib.request
from typing import Any, Callable, Iterator

from .core import LabError, Settings, require_data_mount

ARTIFACT_KEYS = ("model", "draftModel", "multimodalProjector")
CHUNK_BYTES = 8 * 1024 * 1024


def artifact_url(artifact: dict[str, Any]) -> str:
    revision = artifact.get("revision") or "main"
    return f"https://huggingface.co/{artifact['repository']}/resolve/{revision}/{artifact['file']}"


def sha256_of(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


@contextlib.contextmanager
def profile_download_lock(directory: pathlib.Path) -> Iterator[None]:
    # Per-profile lock: different profiles download in parallel, and none blocks start/bench/benchmark.
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".download.lock").open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LabError(f"Ya hay una descarga en curso para {directory.name}", 1) from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def http_fetch(url: str, destination: pathlib.Path, offset: int) -> None:
    request = urllib.request.Request(url)
    token = os.environ.get("HF_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if offset:
        request.add_header("Range", f"bytes={offset}-")
    with urllib.request.urlopen(request, timeout=60) as response:
        # A server that ignores Range answers 200 with the whole file; restart in that case.
        mode = "ab" if offset and response.status == 206 else "wb"
        with destination.open(mode) as handle:
            for block in iter(lambda: response.read(CHUNK_BYTES), b""):
                handle.write(block)


def download_artifact(
    directory: pathlib.Path,
    artifact: dict[str, Any],
    *,
    fetch: Callable[[str, pathlib.Path, int], None] = http_fetch,
    log: Callable[[str], None] = print,
    attempts: int = 5,
) -> pathlib.Path:
    destination = directory / pathlib.Path(artifact["file"]).name
    if not destination.is_file():
        partial = destination.with_name(destination.name + ".part")
        url = artifact_url(artifact)
        log(f"Descargando {artifact['repository']}/{artifact['file']} ({artifact.get('revision') or 'main'})...")
        for attempt in range(1, attempts + 1):
            try:
                fetch(url, partial, partial.stat().st_size if partial.exists() else 0)
                break
            except OSError as exc:
                if attempt == attempts:
                    raise LabError(f"Falló la descarga de {artifact['file']}: {exc}", 1) from exc
                log(f"Reintentando {artifact['file']} ({attempt}/{attempts - 1}): {exc}")
        partial.replace(destination)
    checksum = artifact.get("sha256")
    if checksum and sha256_of(destination) != checksum:
        raise LabError(f"Checksum inválido para {destination}", 5)
    return destination


def download_profile_artifacts(settings: Settings, profile: dict[str, Any], **kwargs: Any) -> list[pathlib.Path]:
    require_data_mount(settings)
    directory = settings.data_dir / "models" / profile["id"]
    with profile_download_lock(directory):
        return [
            download_artifact(directory, profile[key], **kwargs)
            for key in ARTIFACT_KEYS
            if profile.get(key)
        ]

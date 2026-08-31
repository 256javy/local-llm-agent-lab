from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import tempfile
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from ..core import LabError
from .models import SCHEMA_VERSION, utc_now, validate_event


TRACE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: pathlib.Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    path.chmod(0o600)


class TraceStore:
    """Store filesystem local; publica cada trace completo de forma atómica."""

    def __init__(self, root: pathlib.Path):
        self.root = root.expanduser().resolve()
        self.traces_dir = self.root / "traces"

    def create_trace(
        self,
        *,
        source: Mapping[str, Any],
        raw_files: Mapping[str, pathlib.Path],
        events: Iterable[dict[str, Any]],
        trace_id: str | None = None,
        warnings: Iterable[str] = (),
    ) -> pathlib.Path:
        trace_id = trace_id or f"trace-{uuid.uuid4()}"
        self._validate_trace_id(trace_id)
        self._validate_source(source)
        if not raw_files:
            raise LabError("El trace debe preservar al menos un archivo raw", 2)
        normalized_events = list(events)
        event_ids: set[str] = set()
        for sequence, event in enumerate(normalized_events):
            validate_event(event, expected_sequence=sequence)
            if event["eventId"] in event_ids:
                raise LabError(f"eventId duplicado: {event['eventId']}", 2)
            event_ids.add(event["eventId"])

        self.traces_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.traces_dir.chmod(0o700)
        destination = self.traces_dir / trace_id
        if destination.exists():
            raise LabError(f"El trace ya existe y es inmutable: {trace_id}", 1)

        staging = pathlib.Path(tempfile.mkdtemp(prefix=f".{trace_id}-", dir=self.traces_dir))
        staging.chmod(0o700)
        try:
            raw_dir = staging / "raw"
            normalized_dir = staging / "normalized"
            raw_dir.mkdir(mode=0o700)
            normalized_dir.mkdir(mode=0o700)
            raw_entries = self._copy_raw(raw_files, raw_dir)
            events_path = normalized_dir / "events.jsonl"
            with events_path.open("x", encoding="utf-8") as handle:
                for event in normalized_events:
                    handle.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            events_path.chmod(0o600)
            manifest = {
                "schemaVersion": SCHEMA_VERSION,
                "kind": "trace-manifest",
                "traceId": trace_id,
                "createdAt": utc_now(),
                "source": dict(source),
                "raw": raw_entries,
                "normalized": {
                    "eventsPath": "normalized/events.jsonl",
                    "eventCount": len(normalized_events),
                    "sha256": sha256_file(events_path),
                },
                "warnings": list(warnings),
            }
            _write_json(staging / "manifest.json", manifest)
            os.replace(staging, destination)
            return destination
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    @staticmethod
    def _validate_trace_id(trace_id: str) -> None:
        if not TRACE_ID_PATTERN.fullmatch(trace_id) or trace_id in {".", ".."}:
            raise LabError(f"ID de trace inválido: {trace_id}", 2)

    @staticmethod
    def _validate_source(source: Mapping[str, Any]) -> None:
        required = ("client", "version", "captureCommand")
        missing = [field for field in required if not isinstance(source.get(field), str) or not source[field].strip()]
        if missing:
            raise LabError(f"Fuente de trace inválida; faltan campos: {', '.join(missing)}", 2)

    @staticmethod
    def _copy_raw(raw_files: Mapping[str, pathlib.Path], raw_dir: pathlib.Path) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for name, source in sorted(raw_files.items()):
            if not name or pathlib.PurePosixPath(name).name != name or name in {".", ".."}:
                raise LabError(f"Nombre de raw inválido: {name}", 2)
            expanded = source.expanduser()
            if expanded.is_symlink():
                raise LabError(f"El raw no puede ser un enlace simbólico: {source}", 2)
            resolved = expanded.resolve()
            if not resolved.is_file():
                raise LabError(f"El raw no es un archivo regular: {source}", 2)
            destination = raw_dir / name
            with resolved.open("rb") as input_handle, destination.open("xb") as output_handle:
                shutil.copyfileobj(input_handle, output_handle)
                output_handle.flush()
                os.fsync(output_handle.fileno())
            destination.chmod(0o400)
            entries.append({
                "path": f"raw/{name}",
                "bytes": destination.stat().st_size,
                "sha256": sha256_file(destination),
            })
        return entries

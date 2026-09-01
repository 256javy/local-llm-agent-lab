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
        artifacts: Mapping[str, bytes | str] | None = None,
        manifest_fields: Mapping[str, Any] | None = None,
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
            artifact_entries = self._write_artifacts(artifacts or {}, staging)
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
            if artifact_entries:
                manifest["artifacts"] = artifact_entries
            if manifest_fields:
                reserved = set(manifest) & set(manifest_fields)
                if reserved:
                    raise LabError(
                        f"Campos de manifest reservados: {', '.join(sorted(reserved))}", 2
                    )
                manifest.update(manifest_fields)
            _write_json(staging / "manifest.json", manifest)
            os.replace(staging, destination)
            return destination
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def list_traces(self) -> list[dict[str, Any]]:
        if not self.traces_dir.exists():
            return []
        manifests = []
        for path in sorted(self.traces_dir.iterdir()):
            if not path.is_dir() or path.is_symlink() or path.name.startswith("."):
                continue
            manifests.append(self._read_manifest(path.name))
        return sorted(manifests, key=lambda value: (value.get("createdAt", ""), value["traceId"]), reverse=True)

    def show_trace(self, trace_id: str, *, include_events: bool = True) -> dict[str, Any]:
        manifest = self._read_manifest(trace_id)
        if not include_events:
            return manifest
        events_path = self.traces_dir / trace_id / "normalized" / "events.jsonl"
        events: list[dict[str, Any]] = []
        try:
            for line_number, line in enumerate(events_path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError("el evento no es un objeto")
                validate_event(event, expected_sequence=len(events))
                events.append(event)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise LabError(f"No se pudieron leer los eventos de {trace_id}: {exc}", 2) from exc
        if sha256_file(events_path) != manifest["normalized"]["sha256"]:
            raise LabError(f"El hash de eventos no coincide con el manifest: {trace_id}", 2)
        if len(events) != manifest["normalized"]["eventCount"]:
            raise LabError(f"El conteo de eventos no coincide con el manifest: {trace_id}", 2)
        trace_path = self.traces_dir / trace_id
        for entry in manifest["raw"]:
            raw_path = trace_path / entry["path"]
            if raw_path.is_symlink() or not raw_path.is_file() or sha256_file(raw_path) != entry["sha256"]:
                raise LabError(f"La evidencia raw no coincide con el manifest: {entry['path']}", 2)
        for entry in manifest.get("artifacts", []):
            artifact_path = trace_path.joinpath(*pathlib.PurePosixPath(entry["path"]).parts)
            if (
                artifact_path.is_symlink()
                or not artifact_path.is_file()
                or artifact_path.stat().st_size != entry["bytes"]
                or sha256_file(artifact_path) != entry["sha256"]
            ):
                raise LabError(f"El artefacto no coincide con el manifest: {entry['path']}", 2)
        return {"manifest": manifest, "events": events}

    def _read_manifest(self, trace_id: str) -> dict[str, Any]:
        self._validate_trace_id(trace_id)
        trace_path = self.traces_dir / trace_id
        manifest_path = trace_path / "manifest.json"
        if trace_path.is_symlink() or manifest_path.is_symlink() or not manifest_path.is_file():
            raise LabError(f"Trace no encontrado: {trace_id}", 1)
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LabError(f"Manifest de trace inválido ({trace_id}): {exc}", 2) from exc
        if not isinstance(manifest, dict) or manifest.get("traceId") != trace_id or manifest.get("kind") != "trace-manifest":
            raise LabError(f"Manifest de trace inválido: {trace_id}", 2)
        source = manifest.get("source")
        normalized = manifest.get("normalized")
        raw = manifest.get("raw")
        artifacts = manifest.get("artifacts", [])
        if (
            manifest.get("schemaVersion") != SCHEMA_VERSION
            or not isinstance(source, dict)
            or not all(isinstance(source.get(field), str) and source[field] for field in ("client", "version", "captureCommand"))
            or not isinstance(normalized, dict)
            or normalized.get("eventsPath") != "normalized/events.jsonl"
            or not isinstance(normalized.get("eventCount"), int)
            or not isinstance(normalized.get("sha256"), str)
            or not isinstance(raw, list)
            or not all(
                isinstance(item, dict)
                and isinstance(item.get("path"), str)
                and len(pathlib.PurePosixPath(item["path"]).parts) == 2
                and pathlib.PurePosixPath(item["path"]).parts[0] == "raw"
                and pathlib.PurePosixPath(item["path"]).name not in {".", ".."}
                and isinstance(item.get("sha256"), str)
                for item in raw
            )
            or not isinstance(artifacts, list)
            or not all(
                isinstance(item, dict)
                and isinstance(item.get("path"), str)
                and self._safe_artifact_path(item["path"])
                and isinstance(item.get("bytes"), int)
                and isinstance(item.get("sha256"), str)
                for item in artifacts
            )
        ):
            raise LabError(f"Manifest de trace inválido: {trace_id}", 2)
        return manifest

    @staticmethod
    def _safe_artifact_path(value: str) -> bool:
        path = pathlib.PurePosixPath(value)
        return (
            bool(value)
            and not path.is_absolute()
            and len(path.parts) >= 2
            and all(part not in {"", ".", ".."} for part in path.parts)
            and path.parts[0] not in {"raw", "normalized"}
        )

    @classmethod
    def _write_artifacts(
        cls, artifacts: Mapping[str, bytes | str], staging: pathlib.Path
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for relative, content in sorted(artifacts.items()):
            if not cls._safe_artifact_path(relative):
                raise LabError(f"Ruta de artefacto inválida: {relative}", 2)
            destination = staging.joinpath(*pathlib.PurePosixPath(relative).parts)
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            destination.parent.chmod(0o700)
            data = content.encode("utf-8") if isinstance(content, str) else content
            with destination.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            destination.chmod(0o600)
            entries.append({
                "path": relative,
                "bytes": len(data),
                "sha256": sha256_file(destination),
            })
        return entries

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

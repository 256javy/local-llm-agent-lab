from __future__ import annotations

import json
import os
import pathlib
import tempfile
import uuid
from collections.abc import Mapping
from typing import Any

from ..core import LabError
from .context import collect_effective_context
from .models import SCHEMA_VERSION, utc_now
from .repository import capture_repository_snapshot
from .redact import REDACTION_WARNING, RedactionConfig, redact_files
from .store import TraceStore


CLIENTS = {"pi", "opencode"}


def _write_private_json(path: pathlib.Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _active_files(store: TraceStore) -> list[pathlib.Path]:
    active_dir = store.root / "active"
    if not active_dir.exists():
        return []
    return [path for path in active_dir.glob("*.json") if path.is_file() and not path.is_symlink()]


def _capture_untracked(
    snapshot: Mapping[str, Any],
    *,
    include_content: bool,
    max_file_bytes: int,
    max_total_bytes: int,
) -> dict[str, Any]:
    untracked = snapshot.get("untracked", {})
    repository = snapshot.get("repository", {})
    paths = untracked.get("paths", []) if isinstance(untracked, Mapping) else []
    root = repository.get("root") if isinstance(repository, Mapping) else None
    if not include_content or not root or not isinstance(paths, list):
        return {
            "contentIncluded": False,
            "files": {},
            "report": {
                "matches": {},
                "omissions": [],
                "warnings": [REDACTION_WARNING],
                "scannedBytes": 0,
            },
        }
    result = redact_files(
        [path for path in paths if isinstance(path, str)],
        root=pathlib.Path(root),
        config=RedactionConfig(max_file_bytes=max_file_bytes, max_total_bytes=max_total_bytes),
    )
    return {
        "contentIncluded": True,
        "files": {
            path: redacted.content
            for path, redacted in result.files.items()
            if redacted.content is not None
        },
        "report": result.report.as_dict(),
    }


def begin_exact_capture(
    store: TraceStore,
    *,
    client: str,
    repository: pathlib.Path,
    trace_id: str | None = None,
    confirmations: Mapping[str, Mapping[str, Any]] | None = None,
    include_untracked: bool = False,
    max_file_bytes: int = 1_048_576,
    max_total_bytes: int = 10_485_760,
) -> dict[str, Any]:
    if client not in CLIENTS:
        raise LabError(f"Cliente no soportado para captura exacta: {client}", 2)
    if max_file_bytes < 0 or max_total_bytes < 0:
        raise LabError("Los límites de contenido untracked deben ser enteros no negativos", 2)
    trace_id = trace_id or f"trace-{uuid.uuid4()}"
    store._validate_trace_id(trace_id)
    active = _active_files(store)
    if active:
        raise LabError(f"Ya existe una captura abierta: {active[0].stem}; finalízala primero", 1)
    if (store.traces_dir / trace_id).exists():
        raise LabError(f"El trace ya existe y es inmutable: {trace_id}", 1)

    requested_repository = repository.expanduser().resolve()
    initial = capture_repository_snapshot(requested_repository)
    workspace = pathlib.Path(initial.get("root") or requested_repository)
    context = collect_effective_context(workspace, client=client, confirmations=confirmations)
    initial_untracked = _capture_untracked(
        initial,
        include_content=include_untracked,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
    )
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "active-trace-capture",
        "traceId": trace_id,
        "client": client,
        "startedAt": utc_now(),
        "requestedRepository": str(requested_repository),
        "initialRepository": initial,
        "effectiveContext": context,
        "untrackedOptions": {
            "includeContent": include_untracked,
            "maxFileBytes": max_file_bytes,
            "maxTotalBytes": max_total_bytes,
        },
        "initialUntracked": initial_untracked,
    }
    active_path = store.root / "active" / f"{trace_id}.json"
    _write_private_json(active_path, payload)
    return {"traceId": trace_id, "startedAt": payload["startedAt"], "activePath": str(active_path)}


def finish_exact_capture(store: TraceStore, trace_id: str) -> pathlib.Path:
    store._validate_trace_id(trace_id)
    active_path = store.root / "active" / f"{trace_id}.json"
    if active_path.is_symlink() or not active_path.is_file():
        raise LabError(f"No existe una captura abierta con ID: {trace_id}", 1)
    try:
        active = json.loads(active_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LabError(f"Estado de captura exacta inválido ({trace_id}): {exc}", 2) from exc
    if (
        not isinstance(active, dict)
        or active.get("schemaVersion") != SCHEMA_VERSION
        or active.get("kind") != "active-trace-capture"
        or active.get("traceId") != trace_id
        or active.get("client") not in CLIENTS
    ):
        raise LabError(f"Estado de captura exacta inválido: {trace_id}", 2)

    repository = pathlib.Path(active["requestedRepository"])
    final = capture_repository_snapshot(repository)
    options = active.get("untrackedOptions", {})
    final_untracked = _capture_untracked(
        final,
        include_content=bool(options.get("includeContent")),
        max_file_bytes=int(options.get("maxFileBytes", 1_048_576)),
        max_total_bytes=int(options.get("maxTotalBytes", 10_485_760)),
    )
    finished_at = utc_now()
    capture_record = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "exact-capture-record",
        "traceId": trace_id,
        "client": active["client"],
        "startedAt": active["startedAt"],
        "finishedAt": finished_at,
    }
    rendered = lambda value: json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with tempfile.TemporaryDirectory(prefix="llm-lab-exact-") as temporary:
        raw = pathlib.Path(temporary) / "capture.json"
        raw.write_text(rendered(capture_record), encoding="utf-8")
        artifacts = {
            "repository/initial/snapshot.json": rendered(active["initialRepository"]),
            "repository/final/snapshot.json": rendered(final),
            "repository/initial/untracked-report.json": rendered(active["initialUntracked"]["report"]),
            "repository/final/untracked-report.json": rendered(final_untracked["report"]),
            "effective-context/context.json": rendered(active["effectiveContext"]),
        }
        for phase, captured in (("initial", active["initialUntracked"]), ("final", final_untracked)):
            for relative, content in captured["files"].items():
                artifacts[f"repository/{phase}/untracked/{relative}"] = content
        destination = store.create_trace(
            trace_id=trace_id,
            source={
                "client": active["client"],
                "version": "unknown",
                "captureCommand": f"llm-lab trace begin/finish {trace_id}",
            },
            raw_files={"capture.json": raw},
            events=[],
            artifacts=artifacts,
            manifest_fields={
                "captureMode": "exact",
                "capture": {
                    "startedAt": active["startedAt"],
                    "finishedAt": finished_at,
                    "initialRepository": "repository/initial/snapshot.json",
                    "finalRepository": "repository/final/snapshot.json",
                    "effectiveContext": "effective-context/context.json",
                    "untrackedContentOptIn": bool(options.get("includeContent")),
                    "redactionWarning": REDACTION_WARNING,
                },
            },
        )
    active_path.unlink()
    try:
        active_path.parent.rmdir()
    except OSError:
        pass
    return destination

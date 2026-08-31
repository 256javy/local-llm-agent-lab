from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from typing import Any

from ..core import LabError
from .adapters import normalize_opencode_export, normalize_pi_jsonl
from .store import TraceStore


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, **kwargs)


def _version(binary: str, runner: Runner) -> str:
    result = runner([binary, "--version"])
    if result.returncode != 0 or not result.stdout.strip():
        raise LabError(f"No se pudo detectar la versión de {binary}: {result.stderr.strip() or 'sin salida'}", 2)
    return result.stdout.strip().splitlines()[0]


def find_pi_session(session: str, sessions_root: pathlib.Path | None = None) -> pathlib.Path:
    direct = pathlib.Path(session).expanduser()
    if direct.is_symlink():
        raise LabError(f"La sesión Pi no puede ser un enlace simbólico: {direct}", 2)
    if direct.is_file():
        return direct.resolve()
    root = (sessions_root or pathlib.Path.home() / ".pi" / "agent" / "sessions").expanduser()
    if not root.is_dir():
        raise LabError(f"No existe el directorio de sesiones Pi: {root}", 1)
    matches: list[pathlib.Path] = []
    for candidate in root.rglob("*.jsonl"):
        if candidate.is_symlink() or not candidate.is_file():
            continue
        if candidate.stem == session or candidate.name == session:
            matches.append(candidate)
            continue
        try:
            first_line = candidate.open(encoding="utf-8").readline()
            header = json.loads(first_line)
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(header, dict) and header.get("type") == "session" and header.get("id") == session:
            matches.append(candidate)
    if not matches:
        raise LabError(f"Sesión Pi no encontrada: {session}", 1)
    if len(matches) > 1:
        raise LabError(f"La sesión Pi no es única ({session}); usa la ruta exacta", 1)
    return matches[0].resolve()


def capture_pi(store: TraceStore, session: str, *, trace_id: str | None = None, runner: Runner = _run, sessions_root: pathlib.Path | None = None) -> pathlib.Path:
    if not shutil.which("pi") and runner is _run:
        raise LabError("Pi no está instalado o no está en PATH", 2)
    source_path = find_pi_session(session, sessions_root)
    metadata, events, warnings = normalize_pi_jsonl(source_path)
    version = _version("pi", runner)
    source = {"client": "pi", "version": version, "captureCommand": f"pi-session {metadata.get('sessionId') or session}", **metadata}
    return store.create_trace(source=source, raw_files={"session.jsonl": source_path}, events=events, trace_id=trace_id, warnings=warnings)


def _opencode_session_ids(payload: Any) -> set[str]:
    if isinstance(payload, list):
        return {str(item["id"]) for item in payload if isinstance(item, dict) and item.get("id")}
    if isinstance(payload, dict):
        values = payload.get("sessions")
        if isinstance(values, list):
            return {str(item["id"]) for item in values if isinstance(item, dict) and item.get("id")}
    raise LabError("`opencode session list --format json` devolvió un formato no soportado", 2)


def capture_opencode(store: TraceStore, session: str, *, trace_id: str | None = None, runner: Runner = _run) -> pathlib.Path:
    if not shutil.which("opencode") and runner is _run:
        raise LabError("OpenCode no está instalado o no está en PATH", 2)
    version = _version("opencode", runner)
    list_help = runner(["opencode", "session", "list", "--help"])
    export_help = runner(["opencode", "export", "--help"])
    if list_help.returncode != 0 or "--format" not in list_help.stdout:
        raise LabError("Esta versión de OpenCode no soporta `session list --format json`", 2)
    if export_help.returncode != 0 or "sessionID" not in export_help.stdout:
        raise LabError("Esta versión de OpenCode no soporta `export <sessionID>`", 2)
    capabilities = {
        "sessionListJson": True,
        "export": True,
        "sanitize": "--sanitize" in export_help.stdout,
    }
    listed = runner(["opencode", "session", "list", "--format", "json"])
    if listed.returncode != 0:
        raise LabError(f"No se pudieron listar sesiones OpenCode: {listed.stderr.strip() or 'sin detalle'}", 2)
    try:
        session_ids = _opencode_session_ids(json.loads(listed.stdout))
    except json.JSONDecodeError as exc:
        raise LabError(f"Listado JSON de OpenCode inválido: {exc.msg}", 2) from exc
    if session not in session_ids:
        raise LabError(f"Sesión OpenCode no encontrada: {session}", 1)
    exported = runner(["opencode", "export", session])
    if exported.returncode != 0:
        raise LabError(f"No se pudo exportar la sesión OpenCode: {exported.stderr.strip() or 'sin detalle'}", 2)
    with tempfile.TemporaryDirectory(prefix="llm-lab-opencode-") as temporary:
        raw = pathlib.Path(temporary) / "export.json"
        raw.write_text(exported.stdout, encoding="utf-8")
        metadata, events, warnings = normalize_opencode_export(raw)
        if metadata.get("sessionId") not in {None, session}:
            raise LabError(f"El export OpenCode pertenece a otra sesión: {metadata.get('sessionId')}", 2)
        source = {"client": "opencode", "version": version, "captureCommand": f"opencode export {session}", "capabilities": capabilities, **metadata}
        return store.create_trace(source=source, raw_files={"export.json": raw}, events=events, trace_id=trace_id, warnings=warnings)

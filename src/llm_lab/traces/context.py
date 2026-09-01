"""Contrato seguro para registrar el contexto efectivo de un trace.

Esta capa es deliberadamente independiente del store y de la CLI.  ``trace
begin`` y ``trace finish`` pueden invocar :func:`collect_effective_context` y
guardar el resultado sin tener que inferir que un archivo encontrado fue
cargado por Pi u OpenCode.
"""

from __future__ import annotations

import pathlib
import re
from collections.abc import Iterable, Mapping
from typing import Any

from ..core import LabError


SCHEMA_VERSION = 1
CONTEXT_STATES = frozenset({"discovered", "confirmed_loaded", "unknown"})
CONFIRMABLE_FIELDS = frozenset({"model", "profile", "runtime", "system_prompt", "developer_prompt", "tools"})

_SECRET_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?key|token|secret|password|passwd|authorization|credential|private[_-]?key)",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|\bBearer\s+\S+|\b(?:sk|ghp|github_pat)_[A-Za-z0-9_-]+|\b(?:api[_-]?key|access[_-]?key|token|secret|password|passwd)\s*[:=]\s*\S+)",
    re.IGNORECASE,
)


def _relative_path(workspace: pathlib.Path, path: pathlib.Path) -> str:
    try:
        return path.relative_to(workspace).as_posix()
    except ValueError:
        return str(path)


def _discovered_entry(kind: str, name: str, path: pathlib.Path, workspace: pathlib.Path) -> dict[str, Any]:
    """Return filesystem metadata only; configuration and instruction contents are not read."""
    return {
        "kind": kind,
        "name": name,
        "status": "discovered",
        "provenance": "filesystem_discovery",
        "evidence": {
            "kind": "filesystem_metadata",
            "path": _relative_path(workspace, path),
            "isRoot": path.parent == workspace,
        },
    }


def _unknown_entry(field: str) -> dict[str, Any]:
    return {
        "kind": field,
        "status": "unknown",
        "provenance": "unavailable",
        "evidence": {
            "kind": "unavailable",
            "reason": "La fuente capturada no confirma que este contexto haya sido cargado.",
        },
    }


def _safe_value(value: Any, redactions: list[dict[str, str]], *, field: str) -> Any:
    """Copy a confirmed value while omitting likely credentials and their values."""
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            if _SECRET_KEY.search(key_text):
                redactions.append({"field": field, "reason": "secret_key_name"})
                continue
            copied[key_text] = _safe_value(child, redactions, field=field)
        return copied
    if isinstance(value, list):
        return [_safe_value(item, redactions, field=field) for item in value]
    if isinstance(value, tuple):
        return [_safe_value(item, redactions, field=field) for item in value]
    if isinstance(value, str) and _SECRET_VALUE.search(value):
        redactions.append({"field": field, "reason": "secret_value_pattern"})
        return "[REDACTED]"
    return value


def confirmed_loaded_context(confirmations: Mapping[str, Mapping[str, Any]] | None = None) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    """Validate explicit load evidence and return safe, serializable context entries.

    ``confirmations`` has one entry per field, for example::

        {"model": {"value": "local/model", "evidence": {"eventId": "evt-9"}}}

    A discovered file is not valid evidence here.  Evidence must describe an
    observation from the harness/session, such as an event ID, request ID or
    a capture adapter reference.
    """
    if confirmations is None:
        return {}, []
    if not isinstance(confirmations, Mapping):
        raise LabError("Las confirmaciones de contexto deben ser un objeto", 2)

    entries: dict[str, dict[str, Any]] = {}
    redactions: list[dict[str, str]] = []
    for field, confirmation in confirmations.items():
        if field not in CONFIRMABLE_FIELDS:
            raise LabError(f"Campo de contexto no confirmable: {field}", 2)
        if not isinstance(confirmation, Mapping):
            raise LabError(f"La confirmación de {field} debe incluir value y evidence", 2)
        if "value" not in confirmation or not isinstance(confirmation.get("evidence"), Mapping) or not confirmation["evidence"]:
            raise LabError(f"La confirmación de {field} requiere value y evidence explícita", 2)
        evidence = _safe_value(confirmation["evidence"], redactions, field=field)
        entries[field] = {
            "kind": field,
            "status": "confirmed_loaded",
            "provenance": "explicit_observation",
            "value": _safe_value(confirmation["value"], redactions, field=field),
            "evidence": {"kind": "explicit_observation", "source": evidence},
        }
    return entries, redactions


def _client_config_candidates(workspace: pathlib.Path, client: str | None, config_paths: Iterable[pathlib.Path] | None) -> list[tuple[str, pathlib.Path]]:
    if config_paths is not None:
        return [("client_config", pathlib.Path(path).expanduser()) for path in config_paths]
    candidates: list[tuple[str, pathlib.Path]] = []
    requested = {client} if client else {"pi", "opencode"}
    if "pi" in requested:
        candidates.extend(("pi_config", workspace / path) for path in ("pi.json", ".pi/config.json", ".pi/settings.json"))
    if "opencode" in requested:
        candidates.extend(("opencode_config", workspace / path) for path in ("opencode.json", "opencode.jsonc", ".opencode/config.json"))
    return candidates


def discover_effective_context(
    workspace: pathlib.Path,
    *,
    client: str | None = None,
    config_paths: Iterable[pathlib.Path] | None = None,
) -> list[dict[str, Any]]:
    """Discover instruction/configuration files without reading their contents.

    The workspace is the only default search scope.  This intentionally avoids
    traversing home directories, following symlinks, or opening files that
    could contain credentials.  ``client`` may be ``pi`` or ``opencode``.
    """
    if client not in {None, "pi", "opencode"}:
        raise LabError(f"Cliente de contexto no soportado: {client}", 2)
    root = pathlib.Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise LabError(f"El workspace de contexto no es un directorio: {root}", 2)

    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("AGENTS.md")):
        if path.is_symlink() or not path.is_file():
            continue
        name = "root_rules" if path.parent == root else "nested_rules"
        entries.append(_discovered_entry("rule", name, path, root))
    for kind, candidate in _client_config_candidates(root, client, config_paths):
        path = candidate.resolve() if candidate.exists() and not candidate.is_symlink() else candidate
        if path.is_symlink() or not path.is_file():
            continue
        entries.append(_discovered_entry("client_config", kind, path, root))
    return entries


def collect_effective_context(
    workspace: pathlib.Path,
    *,
    client: str | None = None,
    config_paths: Iterable[pathlib.Path] | None = None,
    confirmations: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a schema-v1 snapshot suitable for trace begin/finish metadata."""
    root = pathlib.Path(workspace).expanduser().resolve()
    discovered = discover_effective_context(root, client=client, config_paths=config_paths)
    confirmed, redactions = confirmed_loaded_context(confirmations)
    fields = [confirmed.get(field, _unknown_entry(field)) for field in sorted(CONFIRMABLE_FIELDS)]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "effective-context",
        "workspace": str(root),
        "client": client,
        "entries": [*discovered, *fields],
        "redactions": redactions,
    }

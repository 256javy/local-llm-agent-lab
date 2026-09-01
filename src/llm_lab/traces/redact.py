"""Redacción conservadora de evidencia antes de exportarla.

Este módulo no es un sistema DLP.  Su objetivo es reducir filtraciones
accidentales en bundles de trazas; los consumidores deben revisar el resultado
antes de compartirlo fuera de la máquina.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
import os
from pathlib import Path, PurePosixPath
import re
from typing import Final


REDACTION_WARNING: Final = (
    "La redacción es heurística y no sustituye una solución DLP ni una revisión humana."
)

_PRIVATE_KEY = re.compile(
    r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----.*?-----END(?: [A-Z0-9]+)? PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_URL_CREDENTIALS = re.compile(
    r"(?P<prefix>\b[a-z][a-z0-9+.-]*://)(?:[^\s/@:]+(?::[^\s/@]*)?@)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?P<prefix>\bBearer\s+)(?P<value>[^\s,;]+)", re.IGNORECASE)
_ASSIGNMENT = re.compile(
    r"(?P<prefix>\b(?:(?:[a-z][a-z0-9]*_)+)?(?:api[_-]?key|access[_-]?token|"
    r"auth(?:orization)?[_-]?token|client[_-]?secret|secret(?:[_-]?(?:access[_-]?)?key)?|"
    r"password|passwd|pwd|private[_-]?key|key)\b"
    r"\s*(?:=|:)\s*)(?P<value>\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;}\]]+)",
    re.IGNORECASE,
)
_KNOWN_TOKEN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_-]{12,}|"
    r"xox(?:[abprs]|oa)-[A-Za-z0-9-]{12,})\b"
)

# Componentes de rutas que no constituyen evidencia apta para exportar.  Se
# comparan en minúsculas y por componente, no por un substring del nombre.
_EXCLUDED_COMPONENTS: Final = frozenset(
    {
        ".git",
        ".local",
        ".cache",
        ".credentials",
        ".credenciales",
        ".models",
        ".modelos",
        "cache",
        "caches",
        "model",
        "models",
        "modelo",
        "modelos",
        "credential",
        "credentials",
        "credencial",
        "credenciales",
        "secret",
        "secrets",
    }
)


@dataclass(frozen=True)
class RedactionConfig:
    """Límites y exclusiones para la inspección de archivos.

    Los límites se aplican a bytes, antes de decodificar.  Un límite ``None``
    desactiva únicamente ese límite.
    """

    max_file_bytes: int | None = 1_048_576
    max_total_bytes: int | None = 10_485_760
    excluded_components: frozenset[str] = _EXCLUDED_COMPONENTS

    def __post_init__(self) -> None:
        for name, value in (
            ("max_file_bytes", self.max_file_bytes),
            ("max_total_bytes", self.max_total_bytes),
        ):
            if value is not None and (not isinstance(value, int) or value < 0):
                raise ValueError(f"{name} debe ser un entero no negativo o None")


@dataclass(frozen=True)
class RedactionOmission:
    """Un archivo no incluido, sin reproducir jamás su contenido."""

    path: str
    reason: str


@dataclass(frozen=True)
class RedactionReport:
    """Resumen seguro: tipos y cantidades, nunca los valores encontrados."""

    matches: dict[str, int] = field(default_factory=dict)
    omissions: tuple[RedactionOmission, ...] = ()
    warnings: tuple[str, ...] = (REDACTION_WARNING,)
    scanned_bytes: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "matches": dict(self.matches),
            "omissions": [
                {"path": omission.path, "reason": omission.reason} for omission in self.omissions
            ],
            "warnings": list(self.warnings),
            "scannedBytes": self.scanned_bytes,
        }


@dataclass(frozen=True)
class RedactionResult:
    """Contenido apto para exportar junto a su reporte de redacción."""

    content: str | None
    report: RedactionReport


@dataclass(frozen=True)
class RedactedFiles:
    """Resultados de varios archivos, con un límite total compartido."""

    files: dict[str, RedactionResult]
    report: RedactionReport


def redact_text(text: str) -> RedactionResult:
    """Redacta secretos comunes de ``text`` sin conservar sus valores en el reporte."""
    if not isinstance(text, str):
        raise TypeError("text debe ser un string")

    counts: Counter[str] = Counter()
    content = text
    content = _replace(content, _PRIVATE_KEY, "private_key", counts)
    content = _replace_url_credentials(content, counts)
    content = _replace(content, _BEARER, "token", counts)
    content = _replace_assignments(content, counts)
    content = _replace(content, _KNOWN_TOKEN, "token", counts)
    return RedactionResult(
        content=content,
        report=RedactionReport(matches=dict(sorted(counts.items())), scanned_bytes=len(text.encode("utf-8"))),
    )


def redact_file(path: str | Path, *, root: str | Path | None = None, config: RedactionConfig | None = None) -> RedactionResult:
    """Lee y redacta un archivo regular, o devuelve una omisión segura.

    Si se proporciona ``root``, el archivo debe estar debajo de ese directorio y
    todas las rutas del reporte se expresan como POSIX relativo a él.
    """
    config = config or RedactionConfig()
    candidate = Path(path).expanduser()
    if root is not None and not candidate.is_absolute():
        candidate = Path(root).expanduser() / candidate
    display_path = _safe_relative_path(candidate, root)
    if _contains_symlink(candidate):
        return _omitted(display_path, "symlink_rejected")
    if _is_excluded(display_path, config):
        return _omitted(display_path, "excluded_path")
    try:
        resolved = candidate.resolve(strict=True)
        if not resolved.is_file():
            return _omitted(display_path, "not_regular_file")
        if root is not None:
            root_path = Path(root).expanduser().resolve(strict=True)
            try:
                resolved.relative_to(root_path)
            except ValueError:
                return _omitted(display_path, "outside_root")
        size = resolved.stat().st_size
        if config.max_file_bytes is not None and size > config.max_file_bytes:
            return _omitted(display_path, "file_limit_exceeded")
        raw = resolved.read_bytes()
    except (OSError, ValueError):
        return _omitted(display_path, "unreadable_file")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return _omitted(display_path, "non_text_file")

    redacted = redact_text(text)
    return RedactionResult(
        content=redacted.content,
        report=RedactionReport(
            matches=redacted.report.matches,
            warnings=redacted.report.warnings,
            scanned_bytes=len(raw),
        ),
    )


def redact_files(
    paths: Iterable[str | Path], *, root: str | Path, config: RedactionConfig | None = None
) -> RedactedFiles:
    """Redacta archivos bajo ``root`` aplicando límites por archivo y total.

    Los archivos omitidos aparecen solamente en el reporte agregado. Cada
    entrada incluida usa una clave relativa segura y contenido ya redactado.
    """
    config = config or RedactionConfig()
    included: dict[str, RedactionResult] = {}
    counts: Counter[str] = Counter()
    omissions: list[RedactionOmission] = []
    scanned_bytes = 0
    for path in paths:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = Path(root).expanduser() / candidate
        display_path = _safe_relative_path(candidate, root)
        result = redact_file(candidate, root=root, config=config)
        if result.content is None:
            omissions.extend(result.report.omissions)
            continue
        next_total = scanned_bytes + result.report.scanned_bytes
        if config.max_total_bytes is not None and next_total > config.max_total_bytes:
            omissions.append(RedactionOmission(display_path, "total_limit_exceeded"))
            continue
        # Una clave duplicada no puede sobrescribir contenido ya inspeccionado.
        if display_path in included:
            omissions.append(RedactionOmission(display_path, "duplicate_path"))
            continue
        included[display_path] = result
        counts.update(result.report.matches)
        scanned_bytes = next_total
    report = RedactionReport(
        matches=dict(sorted(counts.items())),
        omissions=tuple(omissions),
        scanned_bytes=scanned_bytes,
    )
    return RedactedFiles(files=included, report=report)


def _replace(content: str, pattern: re.Pattern[str], kind: str, counts: Counter[str]) -> str:
    def replacement(match: re.Match[str]) -> str:
        counts[kind] += 1
        prefix = match.groupdict().get("prefix")
        return f"{prefix or ''}[REDACTED:{kind.upper()}]"

    return pattern.sub(replacement, content)


def _replace_url_credentials(content: str, counts: Counter[str]) -> str:
    def replacement(match: re.Match[str]) -> str:
        counts["url_credentials"] += 1
        return f"{match.group('prefix')}[REDACTED:URL_CREDENTIALS]@"

    return _URL_CREDENTIALS.sub(replacement, content)


def _replace_assignments(content: str, counts: Counter[str]) -> str:
    def replacement(match: re.Match[str]) -> str:
        field = match.group("prefix").lower()
        if any(name in field for name in ("password", "passwd", "pwd")):
            kind = "password"
        elif "token" in field:
            kind = "token"
        elif "key" in field:
            kind = "key"
        else:
            kind = "secret"
        counts[kind] += 1
        return f"{match.group('prefix')}[REDACTED:{kind.upper()}]"

    return _ASSIGNMENT.sub(replacement, content)


def _omitted(path: str, reason: str) -> RedactionResult:
    return RedactionResult(
        content=None,
        report=RedactionReport(omissions=(RedactionOmission(path=path, reason=reason),)),
    )


def _safe_relative_path(path: Path, root: str | Path | None) -> str:
    """Devuelve una ruta de reporte no absoluta ni navegable."""
    try:
        if root is not None:
            root_path = Path(root).expanduser().resolve(strict=False)
            candidate = Path(os.path.abspath(path))
            return candidate.relative_to(root_path).as_posix()
    except (OSError, ValueError):
        pass
    # Un path absoluto fuera de root no se expone tal cual en el reporte.
    if path.is_absolute():
        return path.name or "file"
    normalized = PurePosixPath(path.as_posix())
    if any(part == ".." for part in normalized.parts):
        return path.name or "file"
    return normalized.as_posix()


def _is_excluded(relative_path: str, config: RedactionConfig) -> bool:
    path = PurePosixPath(relative_path)
    parts = [part.lower() for part in path.parts]
    if any(part in config.excluded_components for part in parts):
        return True
    name = path.name.lower()
    return name == ".env" or name.startswith(".env.")


def _contains_symlink(path: Path) -> bool:
    """No sigue enlaces, tampoco en directorios intermedios."""
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            return True
    return False

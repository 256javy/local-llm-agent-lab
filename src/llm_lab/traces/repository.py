"""Captura de evidencia Git para trazas, sin alterar el checkout.

El módulo sólo inspecciona el repositorio.  La copia, redacción y exportación de
esta evidencia se resuelven en capas posteriores: los parches pueden contener
contenido de archivos ya rastreados, mientras que el inventario de archivos no
rastreados nunca lee su contenido.
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ..core import LabError


Runner = Callable[..., subprocess.CompletedProcess[str]]
SNAPSHOT_STATES = frozenset({"captured", "inferred", "unavailable"})
_NOT_A_REPOSITORY = re.compile(r"not a git repository", re.IGNORECASE)
_SUBMODULE_STATUS = re.compile(r"^([ +\-U])([0-9a-f]{40,64})\s+(.*)$")


def _run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Ejecuta Git sin locks opcionales que puedan refrescar el índice."""
    environment = dict(os.environ)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(command, text=True, capture_output=True, env=environment, **kwargs)


def _detail(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "sin detalle").strip()


def _git(
    directory: pathlib.Path,
    arguments: list[str],
    runner: Runner,
    *,
    allowed_returncodes: tuple[int, ...] = (),
) -> subprocess.CompletedProcess[str]:
    command = ["git", "-C", str(directory), *arguments]
    try:
        result = runner(command)
    except FileNotFoundError as exc:
        raise LabError("Git no está instalado o no está en PATH", 2) from exc
    except PermissionError as exc:
        raise LabError(f"Permiso denegado al inspeccionar el repositorio: {directory}", 2) from exc
    except subprocess.TimeoutExpired as exc:
        raise LabError(f"Timeout al inspeccionar el repositorio: {directory}", 1) from exc
    except OSError as exc:
        raise LabError(f"No se pudo inspeccionar el repositorio {directory}: {exc}", 2) from exc
    if result.returncode and result.returncode not in allowed_returncodes:
        raise LabError(f"Git no pudo inspeccionar el repositorio: {_detail(result)}", 2)
    return result


def _part(state: str, **values: Any) -> dict[str, Any]:
    return {"state": state, **values}


def _unavailable_snapshot(reason: str) -> dict[str, Any]:
    unavailable = lambda: _part("unavailable", reason=reason)
    return {
        "schemaVersion": 1,
        "kind": "git-repository-snapshot",
        "state": "unavailable",
        "repository": unavailable(),
        "head": unavailable(),
        "ref": unavailable(),
        "remotes": unavailable(),
        "submodules": unavailable(),
        "status": unavailable(),
        "patches": unavailable(),
        "untracked": unavailable(),
    }


def _sanitize_remote_url(value: str) -> str:
    """Quita userinfo, query y fragmentos que pueden contener credenciales."""
    value = value.strip()
    parsed = urlsplit(value)
    if parsed.scheme and parsed.netloc:
        # ``hostname`` también elimina user:password@. Conservamos el puerto si
        # es válido; para un netloc inusual se conserva sólo la porción posterior
        # al último arroba, que es igualmente libre de userinfo.
        try:
            host = parsed.hostname or ""
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            if parsed.port is not None:
                host = f"{host}:{parsed.port}"
        except ValueError:
            host = parsed.netloc.rsplit("@", 1)[-1]
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    if "@" in value and not value.startswith("@"):
        # Sintaxis SCP de Git: usuario@host:organizacion/repositorio.git.
        return value.split("@", 1)[-1]
    return value.split("#", 1)[0].split("?", 1)[0]


def _remote_urls(directory: pathlib.Path, name: str, runner: Runner, *, push: bool) -> list[str]:
    arguments = ["remote", "get-url", "--all"]
    if push:
        arguments.append("--push")
    arguments.append(name)
    result = _git(directory, arguments, runner)
    return sorted({_sanitize_remote_url(line) for line in result.stdout.splitlines() if line.strip()})


def _submodules(output: str) -> list[dict[str, str]]:
    states = {" ": "clean", "-": "uninitialized", "+": "modified", "U": "conflicted"}
    entries: list[dict[str, str]] = []
    for raw_line in output.splitlines():
        match = _SUBMODULE_STATUS.match(raw_line)
        if not match:
            entries.append({"checkoutState": "unknown", "raw": raw_line})
            continue
        marker, commit, remainder = match.groups()
        # Git añade opcionalmente `` (heads/<ref>)``. El path se conserva tal
        # cual para no reconstruir ni normalizar nombres válidos con espacios.
        path = remainder.rsplit(" (", 1)[0] if " (" in remainder else remainder
        entries.append({"path": path, "commit": commit, "checkoutState": states[marker]})
    return entries


def _safe_untracked_paths(output: str) -> list[str]:
    paths: list[str] = []
    for raw_path in output.split("\0"):
        if not raw_path:
            continue
        path = pathlib.PurePosixPath(raw_path)
        if path.is_absolute() or any(part in {"", ".", "..", ".git"} for part in path.parts):
            continue
        paths.append(raw_path)
    return sorted(paths)


def _status_summary(porcelain_v2: str, untracked_count: int) -> dict[str, bool | int]:
    staged = False
    unstaged = False
    for line in porcelain_v2.splitlines():
        if not line or line.startswith("#") or line[0] not in {"1", "2", "u"}:
            continue
        fields = line.split(" ", 3)
        xy = fields[1] if len(fields) > 1 else ".."
        staged = staged or (len(xy) >= 1 and xy[0] != ".")
        unstaged = unstaged or (len(xy) >= 2 and xy[1] != ".")
    dirty = staged or unstaged or bool(untracked_count)
    return {
        "clean": not dirty,
        "dirty": dirty,
        "staged": staged,
        "unstaged": unstaged,
        "untracked": bool(untracked_count),
        "untrackedCount": untracked_count,
    }


def capture_repository_snapshot(
    directory: pathlib.Path | str,
    *,
    runner: Runner = _run,
    state: str = "captured",
) -> dict[str, Any]:
    """Devuelve un snapshot Git de sólo lectura del directorio indicado.

    ``state`` permite a un consumidor marcar una observación posterior como
    ``inferred``; una captura en vivo usa el valor predeterminado ``captured``.
    Para un directorio fuera de Git el resultado completo queda ``unavailable``
    en vez de inventar una revisión o una rama.
    """
    if state not in SNAPSHOT_STATES - {"unavailable"}:
        raise LabError("El estado del snapshot debe ser captured o inferred", 2)
    source = pathlib.Path(directory).expanduser()
    try:
        resolved = source.resolve()
    except OSError as exc:
        raise LabError(f"No se pudo resolver el directorio del repositorio: {source}", 2) from exc
    if not resolved.exists():
        raise LabError(f"No existe el directorio del repositorio: {resolved}", 2)
    if not resolved.is_dir():
        raise LabError(f"La ruta del repositorio debe ser un directorio: {resolved}", 2)

    root_result = _git(resolved, ["rev-parse", "--show-toplevel"], runner, allowed_returncodes=(128,))
    if root_result.returncode == 128:
        if _NOT_A_REPOSITORY.search(_detail(root_result)):
            return _unavailable_snapshot("not_git_repository")
        raise LabError(f"Git no pudo inspeccionar el repositorio: {_detail(root_result)}", 2)
    root = pathlib.Path(root_result.stdout.strip()).resolve()

    head_result = _git(root, ["rev-parse", "--verify", "HEAD"], runner, allowed_returncodes=(128,))
    head = (
        _part(state, value=head_result.stdout.strip())
        if head_result.returncode == 0
        else _part("unavailable", reason="head_unavailable")
    )
    ref_result = _git(root, ["symbolic-ref", "--quiet", "--short", "HEAD"], runner, allowed_returncodes=(1,))
    ref = (
        _part(state, kind="branch", name=ref_result.stdout.strip())
        if ref_result.returncode == 0
        else _part(state, kind="detached", name=None)
    )

    remote_names = [line for line in _git(root, ["remote"], runner).stdout.splitlines() if line]
    remotes = [
        {
            "name": name,
            "fetchUrls": _remote_urls(root, name, runner, push=False),
            "pushUrls": _remote_urls(root, name, runner, push=True),
        }
        for name in remote_names
    ]
    submodules = _submodules(_git(root, ["submodule", "status", "--recursive", "--cached"], runner).stdout)
    porcelain_v2 = _git(root, ["status", "--porcelain=v2", "--branch", "--untracked-files=all"], runner).stdout
    untracked = _safe_untracked_paths(_git(root, ["ls-files", "--others", "--exclude-standard", "-z"], runner).stdout)
    staged_patch = _git(root, ["diff", "--cached", "--no-ext-diff", "--binary"], runner).stdout
    unstaged_patch = _git(root, ["diff", "--no-ext-diff", "--binary"], runner).stdout

    return {
        "schemaVersion": 1,
        "kind": "git-repository-snapshot",
        "state": state,
        "repository": _part(state, root=str(root)),
        "head": head,
        "ref": ref,
        "remotes": _part(state, items=remotes),
        "submodules": _part(state, items=submodules),
        "status": _part(state, porcelainV2=porcelain_v2, summary=_status_summary(porcelain_v2, len(untracked))),
        "patches": _part(state, staged=staged_patch, unstaged=unstaged_patch),
        "untracked": _part(state, paths=untracked, contentIncluded=False),
    }

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import pathlib
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterator


class LabError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class Settings:
    repo_dir: pathlib.Path
    host: str
    port: int
    data_dir: pathlib.Path
    archive_dir: pathlib.Path | None
    cuda_architectures: str
    default_profile: str
    api_key: str
    start_timeout: int
    stop_timeout: int

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}/v1"

    @property
    def state_dir(self) -> pathlib.Path:
        base = pathlib.Path(os.environ.get("XDG_STATE_HOME", pathlib.Path.home() / ".local/state"))
        return base / "local-llm-agent-lab"

    @property
    def state_file(self) -> pathlib.Path:
        return self.state_dir / "state.json"

    @property
    def lock_file(self) -> pathlib.Path:
        return self.state_dir / "control.lock"


def parse_env_file(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_settings(repo_dir: pathlib.Path) -> Settings:
    file_values = parse_env_file(repo_dir / ".env")

    def value(name: str, default: str) -> str:
        return os.environ.get(name, file_values.get(name, default))

    data_raw = value("LLM_LAB_DATA_DIR", "")
    data_dir = pathlib.Path(data_raw).expanduser() if data_raw else pathlib.Path(
        os.environ.get("XDG_DATA_HOME", pathlib.Path.home() / ".local/share")
    ) / "local-llm-agent-lab"
    archive_raw = value("LLM_LAB_ARCHIVE_DIR", "")
    archive_dir = pathlib.Path(archive_raw).expanduser().resolve() if archive_raw else None
    try:
        port = int(value("LLM_LAB_PORT", "18080"))
        start_timeout = int(value("LLM_LAB_START_TIMEOUT", "900"))
        stop_timeout = int(value("LLM_LAB_STOP_TIMEOUT", "60"))
    except ValueError as exc:
        raise LabError(f"Configuración numérica inválida: {exc}", 2) from exc
    if not 1 <= port <= 65535:
        raise LabError(f"Puerto fuera de rango: {port}", 2)
    return Settings(
        repo_dir=repo_dir,
        host=value("LLM_LAB_HOST", "127.0.0.1"),
        port=port,
        data_dir=data_dir.resolve(),
        archive_dir=archive_dir,
        cuda_architectures=value("LLM_LAB_CUDA_ARCHITECTURES", ""),
        default_profile=value("LLM_LAB_DEFAULT_PROFILE", "gemma-4-12b-qat-mtp"),
        api_key=value("LLM_LAB_API_KEY", ""),
        start_timeout=start_timeout,
        stop_timeout=stop_timeout,
    )


def profile_files(repo_dir: pathlib.Path) -> list[pathlib.Path]:
    return sorted((repo_dir / "config/profiles").glob("*.json"))


def validate_profile(profile: dict[str, Any], source: str = "perfil") -> list[str]:
    errors: list[str] = []
    required = {"id", "displayName", "runtime", "model", "server", "requirements", "capabilities", "status"}
    missing = sorted(required - profile.keys())
    if missing:
        errors.append(f"{source}: faltan campos: {', '.join(missing)}")
        return errors
    if profile["status"] not in {"stable", "candidate", "experimental"}:
        errors.append(f"{source}: status inválido")
    runtime = profile.get("runtime", {})
    for field in ("adapter", "repository", "revision"):
        if not runtime.get(field):
            errors.append(f"{source}: runtime.{field} es obligatorio")
    if runtime.get("adapter") != "llama-cpp":
        errors.append(f"{source}: adaptador no soportado: {runtime.get('adapter')}")
    for artifact_name in ("model", "draftModel"):
        artifact = profile.get(artifact_name)
        if artifact is None:
            continue
        if not artifact.get("repository") or "/" not in artifact.get("repository", ""):
            errors.append(f"{source}: {artifact_name}.repository inválido")
        if not artifact.get("file"):
            errors.append(f"{source}: {artifact_name}.file es obligatorio")
        checksum = artifact.get("sha256")
        if checksum and (len(checksum) != 64 or any(char not in "0123456789abcdefABCDEF" for char in checksum)):
            errors.append(f"{source}: {artifact_name}.sha256 inválido")
    server = profile.get("server", {})
    if not isinstance(server.get("contextSize"), int) or server.get("contextSize", 0) < 1024:
        errors.append(f"{source}: server.contextSize inválido")
    if not isinstance(server.get("parallel"), int) or server.get("parallel", 0) < 1:
        errors.append(f"{source}: server.parallel inválido")
    if not isinstance(server.get("arguments"), list) or not all(isinstance(arg, str) for arg in server.get("arguments", [])):
        errors.append(f"{source}: server.arguments debe ser una lista de strings")
    return errors


def load_profiles(repo_dir: pathlib.Path) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for path in profile_files(repo_dir):
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: {exc}")
            continue
        errors.extend(validate_profile(profile, str(path)))
        profile_id = profile.get("id")
        if profile_id in profiles:
            errors.append(f"ID de perfil duplicado: {profile_id}")
        elif profile_id:
            profile["_path"] = str(path.resolve())
            profiles[profile_id] = profile
    if errors:
        raise LabError("Perfiles inválidos:\n- " + "\n- ".join(errors), 2)
    return profiles


def get_profile(settings: Settings, profile_id: str) -> dict[str, Any]:
    profiles = load_profiles(settings.repo_dir)
    if profile_id not in profiles:
        raise LabError(f"Perfil desconocido: {profile_id}", 2)
    return profiles[profile_id]


def run(command: list[str], *, cwd: pathlib.Path | None = None, env: dict[str, str] | None = None,
        check: bool = True, capture: bool = False, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=check,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise LabError(f"Comando no disponible: {command[0]}", 3) from exc
    except subprocess.TimeoutExpired as exc:
        raise LabError(f"Timeout ejecutando: {' '.join(command)}", 1) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip() if capture else ""
        suffix = f": {detail}" if detail else ""
        raise LabError(f"Falló el comando {' '.join(command)}{suffix}", 1) from exc


def compose_env(settings: Settings, profile: dict[str, Any]) -> dict[str, str]:
    cmake_args = list(profile["runtime"].get("cmakeArgs", []))
    if settings.cuda_architectures:
        cmake_args = [arg for arg in cmake_args if not arg.startswith("-DCMAKE_CUDA_ARCHITECTURES=")]
        cmake_args.append(f"-DCMAKE_CUDA_ARCHITECTURES={settings.cuda_architectures}")
    env = os.environ.copy()
    env.update({
        "LLM_LAB_HOST": settings.host,
        "LLM_LAB_PORT": str(settings.port),
        "LLM_LAB_DATA_DIR": str(settings.data_dir),
        "LLM_LAB_PROFILE_FILE": profile["_path"],
        "LLM_LAB_RUNTIME_REPOSITORY": profile["runtime"]["repository"],
        "LLM_LAB_RUNTIME_REVISION": profile["runtime"]["revision"],
        "LLM_LAB_RUNTIME_CMAKE_ARGS": " ".join(cmake_args),
        "LLM_LAB_RUNTIME_IMAGE": f"local/local-llm-agent-lab:{profile['id']}",
        "LLM_LAB_API_KEY": settings.api_key,
    })
    return env


def compose_command(settings: Settings, *args: str) -> list[str]:
    return ["docker", "compose", "-p", "local-llm-agent-lab", "-f", str(settings.repo_dir / "compose.yaml"), *args]


@contextlib.contextmanager
def control_lock(settings: Settings) -> Iterator[None]:
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    with settings.lock_file.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LabError("Otra operación de control está en curso", 1) from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_state(settings: Settings) -> dict[str, Any] | None:
    if not settings.state_file.exists():
        return None
    try:
        return json.loads(settings.state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"state": "unknown", "reason": "state-file-invalid"}


def write_state(settings: Settings, state: dict[str, Any]) -> None:
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    temporary = settings.state_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(settings.state_file)


def clear_state(settings: Settings) -> None:
    if settings.state_file.exists():
        settings.state_file.unlink()


def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def http_json(url: str, api_key: str = "", timeout: float = 5) -> tuple[int, Any]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload: Any = json.loads(body)
        except json.JSONDecodeError:
            payload = body
        return exc.code, payload
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, json.JSONDecodeError) as exc:
        raise LabError(f"Endpoint no disponible: {exc}", 6) from exc


def wait_for_health(settings: Settings) -> dict[str, Any]:
    deadline = time.monotonic() + settings.start_timeout
    last_error = "sin respuesta"
    while time.monotonic() < deadline:
        try:
            code, payload = http_json(f"http://{settings.host}:{settings.port}/health", settings.api_key, 3)
            if code == 200:
                return payload if isinstance(payload, dict) else {"status": "ok"}
            last_error = f"HTTP {code}: {payload}"
        except LabError as exc:
            last_error = str(exc)
        time.sleep(2)
    raise LabError(f"El servidor no quedó saludable: {last_error}", 6)


def docker_container_running() -> bool:
    result = run(
        ["docker", "inspect", "-f", "{{.State.Running}}", "local-llm-agent-lab-server"],
        check=False,
        capture=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def gpu_info() -> dict[str, Any] | None:
    if not shutil.which("nvidia-smi"):
        return None
    result = run(
        ["nvidia-smi", "--query-gpu=name,driver_version,memory.used,memory.total,compute_cap", "--format=csv,noheader,nounits"],
        check=False,
        capture=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    name, driver, used, total, compute = [part.strip() for part in result.stdout.splitlines()[0].split(",", 4)]
    return {"name": name, "driverVersion": driver, "vramUsedMiB": int(used), "vramTotalMiB": int(total), "computeCapability": compute}


def file_sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

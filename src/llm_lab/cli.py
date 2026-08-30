from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import time
from typing import Any

from . import __version__
from .core import (
    LabError,
    Settings,
    clear_state,
    compose_command,
    compose_env,
    control_lock,
    docker_container_running,
    get_profile,
    gpu_info,
    http_json,
    load_profiles,
    load_settings,
    port_available,
    read_state,
    run,
    wait_for_health,
    write_state,
)


def print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def state_payload(settings: Settings) -> dict[str, Any]:
    state = read_state(settings)
    running = docker_container_running() if shutil.which("docker") else False
    if not state:
        return {"state": "idle", "endpoint": settings.endpoint, "containerRunning": running, "gpu": gpu_info()}
    payload = dict(state)
    payload["containerRunning"] = running
    payload["gpu"] = gpu_info()
    if state.get("startedAt"):
        payload["uptimeSeconds"] = max(0, int(time.time() - state["startedAt"]))
    if state.get("state") == "healthy" and not running:
        payload["state"] = "stale"
    return payload


def command_profiles(settings: Settings, args: argparse.Namespace) -> None:
    profiles = load_profiles(settings.repo_dir)
    if args.json:
        print_json([{key: value for key, value in profile.items() if key != "_path"} for profile in profiles.values()])
        return
    print(f"{'PERFIL':34} {'ESTADO':13} {'VRAM':10} NOMBRE")
    for profile in profiles.values():
        req = profile["requirements"]
        print(f"{profile['id']:34} {profile['status']:13} {req['recommendedVramGiB']:>4} GiB   {profile['displayName']}")


def command_config(settings: Settings, args: argparse.Namespace) -> None:
    if args.config_action != "show" or not args.effective:
        raise LabError("Usa: llm-lab config show --effective", 2)
    print_json({
        "host": settings.host,
        "port": settings.port,
        "endpoint": settings.endpoint,
        "dataDir": str(settings.data_dir),
        "archiveDir": str(settings.archive_dir) if settings.archive_dir else None,
        "cudaArchitecturesOverride": settings.cuda_architectures or None,
        "defaultProfile": settings.default_profile,
        "apiKeyConfigured": bool(settings.api_key),
        "startTimeout": settings.start_timeout,
        "stopTimeout": settings.stop_timeout,
    })


def command_doctor(settings: Settings, args: argparse.Namespace) -> None:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    add("profiles", True, f"{len(load_profiles(settings.repo_dir))} perfiles válidos")
    for binary in ("docker", "nvidia-smi", "curl", "jq"):
        path = shutil.which(binary)
        add(binary, bool(path), path or "no encontrado")
    if shutil.which("docker"):
        result = run(["docker", "info"], check=False, capture=True)
        add("docker-daemon", result.returncode == 0, "disponible" if result.returncode == 0 else (result.stderr.strip() or "no disponible"))
        compose = run(["docker", "compose", "version", "--short"], check=False, capture=True)
        add("docker-compose", compose.returncode == 0, compose.stdout.strip() or compose.stderr.strip())
    gpu = gpu_info()
    add("gpu", gpu is not None, json.dumps(gpu, ensure_ascii=False) if gpu else "NVIDIA no disponible")
    state = read_state(settings)
    port_ok = port_available(settings.host, settings.port)
    if state and docker_container_running():
        add("port", True, f"{settings.host}:{settings.port} pertenece al perfil administrado")
    else:
        add("port", port_ok, f"{settings.host}:{settings.port} {'libre' if port_ok else 'ocupado'}")
    try:
        probe = settings.data_dir
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        disk = shutil.disk_usage(probe)
        add("storage", disk.free >= 20 * 1024**3, f"{disk.free / 1024**3:.1f} GiB libres en {settings.data_dir}")
    except OSError as exc:
        add("storage", False, str(exc))
    if args.json:
        print_json({"ok": all(check["ok"] for check in checks), "checks": checks})
    else:
        for check in checks:
            print(f"{'OK' if check['ok'] else 'ERROR'}: {check['name']}: {check['detail']}")
    if not all(check["ok"] for check in checks):
        raise LabError("El diagnóstico encontró requisitos pendientes", 3)


def stop_managed(settings: Settings, profile: dict[str, Any] | None = None) -> None:
    previous_state = read_state(settings) or {}
    env = compose_env(settings, profile) if profile else os.environ.copy()
    run(compose_command(settings, "down", "--remove-orphans", "--timeout", str(settings.stop_timeout)), cwd=settings.repo_dir, env=env)
    deadline = time.monotonic() + settings.stop_timeout
    while docker_container_running() and time.monotonic() < deadline:
        time.sleep(1)
    if docker_container_running():
        raise LabError("El contenedor administrado no se detuvo; no se iniciará otro perfil", 7)
    baseline = previous_state.get("vramBaselineMiB")
    if isinstance(baseline, int):
        deadline = time.monotonic() + settings.stop_timeout
        while time.monotonic() < deadline:
            gpu = gpu_info()
            if gpu is None or gpu["vramUsedMiB"] <= baseline + 512:
                break
            time.sleep(1)
        else:
            raise LabError(
                f"La VRAM no volvió al nivel previo: se esperaban como máximo {baseline + 512} MiB",
                7,
            )
    clear_state(settings)


def start_profile(settings: Settings, profile: dict[str, Any], *, build_only: bool = False) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    env = compose_env(settings, profile)
    if build_only:
        run(compose_command(settings, "build", "server"), cwd=settings.repo_dir, env=env)
        return
    if not port_available(settings.host, settings.port):
        raise LabError(f"El puerto {settings.host}:{settings.port} está ocupado", 4)
    gpu = gpu_info()
    baseline = gpu["vramUsedMiB"] if gpu else None
    state_base = {"profile": profile["id"], "endpoint": settings.endpoint, "runtime": profile["runtime"]["adapter"], "startedAt": time.time(), "vramBaselineMiB": baseline}
    write_state(settings, {"state": "starting", **state_base})
    try:
        run(compose_command(settings, "up", "-d", "--build", "server"), cwd=settings.repo_dir, env=env)
        wait_for_health(settings)
    except Exception:
        write_state(settings, {"state": "failed", **state_base})
        raise
    write_state(settings, {"state": "healthy", **state_base})


def command_start(settings: Settings, args: argparse.Namespace) -> None:
    profile = get_profile(settings, args.profile or settings.default_profile)
    with control_lock(settings):
        state = read_state(settings)
        if state and state.get("state") != "healthy" and state.get("profile") == profile["id"] and docker_container_running():
            wait_for_health(settings)
            write_state(settings, {**state, "state": "healthy"})
            print(f"Perfil reconciliado: {profile['id']} en {settings.endpoint}")
            return
        if state and state.get("state") == "healthy" and docker_container_running():
            if state.get("profile") == profile["id"]:
                print(f"El perfil {profile['id']} ya está activo en {settings.endpoint}")
                return
            raise LabError(f"Ya está activo {state.get('profile')}; usa `llm-lab switch {profile['id']}`", 1)
        start_profile(settings, profile)
    print(f"Perfil activo: {profile['id']} en {settings.endpoint}")


def command_stop(settings: Settings, args: argparse.Namespace) -> None:
    with control_lock(settings):
        state = read_state(settings)
        profile = None
        if state and state.get("profile"):
            try:
                profile = get_profile(settings, state["profile"])
            except LabError:
                profile = None
        if not docker_container_running() and not state:
            print("No hay un perfil administrado activo")
            return
        stop_managed(settings, profile)
    print("Servidor detenido; modelos y caches fueron preservados")


def command_switch(settings: Settings, args: argparse.Namespace) -> None:
    profile = get_profile(settings, args.profile)
    with control_lock(settings):
        state = read_state(settings)
        if state and state.get("profile") == profile["id"] and docker_container_running():
            print(f"El perfil {profile['id']} ya está activo")
            return
        current = get_profile(settings, state["profile"]) if state and state.get("profile") in load_profiles(settings.repo_dir) else None
        if state or docker_container_running():
            stop_managed(settings, current)
        if not port_available(settings.host, settings.port):
            raise LabError(f"El puerto {settings.host}:{settings.port} sigue ocupado por un proceso externo", 4)
        start_profile(settings, profile)
    print(f"Perfil activo: {profile['id']} en {settings.endpoint}")


def command_status(settings: Settings, args: argparse.Namespace) -> None:
    payload = state_payload(settings)
    if args.json:
        print_json(payload)
    else:
        print(f"Estado: {payload['state']}")
        if payload.get("profile"):
            print(f"Perfil: {payload['profile']}")
        print(f"Endpoint: {payload.get('endpoint', settings.endpoint)}")
        print(f"Contenedor activo: {'sí' if payload.get('containerRunning') else 'no'}")
        if payload.get("gpu"):
            gpu = payload["gpu"]
            print(f"GPU: {gpu['name']} — {gpu['vramUsedMiB']}/{gpu['vramTotalMiB']} MiB")


def command_health(settings: Settings, args: argparse.Namespace) -> None:
    code, payload = http_json(f"http://{settings.host}:{settings.port}/health", settings.api_key)
    result = {"ok": code == 200, "statusCode": code, "payload": payload, "endpoint": settings.endpoint}
    if args.json:
        print_json(result)
    else:
        print(f"{'OK' if result['ok'] else 'ERROR'}: HTTP {code}: {payload}")
    if code != 200:
        raise LabError("Servidor no saludable", 6)


def command_logs(settings: Settings, args: argparse.Namespace) -> None:
    command = compose_command(settings, "logs", "--tail", str(args.tail))
    if args.follow:
        command.append("--follow")
    command.append("server")
    run(command, cwd=settings.repo_dir, check=False)


def pi_config(settings: Settings) -> dict[str, Any]:
    models = []
    for profile in load_profiles(settings.repo_dir).values():
        capabilities = profile["capabilities"]
        models.append({
            "id": profile["id"],
            "name": profile["displayName"],
            "reasoning": capabilities["reasoning"] is True,
            "input": ["text"],
            "contextWindow": profile["server"]["contextSize"],
            "maxTokens": min(32768, profile["server"]["contextSize"] // 4),
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        })
    return {"providers": {"local-lab": {"baseUrl": settings.endpoint, "api": "openai-completions", "apiKey": "local", "compat": {"supportsDeveloperRole": False, "supportsReasoningEffort": False, "maxTokensField": "max_tokens"}, "models": models}}}


def opencode_config(settings: Settings) -> dict[str, Any]:
    models = {}
    for profile in load_profiles(settings.repo_dir).values():
        models[profile["id"]] = {"name": profile["displayName"], "limit": {"context": profile["server"]["contextSize"], "output": min(32768, profile["server"]["contextSize"] // 4)}}
    return {"$schema": "https://opencode.ai/config.json", "provider": {"local-lab": {"npm": "@ai-sdk/openai-compatible", "name": "Local LLM Agent Lab", "options": {"baseURL": settings.endpoint, "apiKey": "local"}, "models": models}}}


def command_client_config(settings: Settings, args: argparse.Namespace) -> None:
    if args.client == "pi":
        payload = pi_config(settings)
    elif args.client == "opencode":
        payload = opencode_config(settings)
    else:
        raise LabError(f"Cliente no soportado: {args.client}", 2)
    rendered = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if not args.output:
        print(rendered, end="")
        return
    destination = args.output.expanduser().resolve()
    if destination.exists() and not args.force:
        raise LabError(f"El archivo ya existe: {destination}; usa --force para reemplazarlo", 1)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        backup = destination.with_name(f"{destination.name}.bak-{datetime.date.today().isoformat()}")
        if backup.exists():
            raise LabError(f"El backup del día ya existe: {backup}", 1)
        shutil.copy2(destination, backup)
        print(f"Backup: {backup}")
    destination.write_text(rendered, encoding="utf-8")
    print(destination)


def directory_size(path: pathlib.Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file() and not entry.is_symlink():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


def command_storage(settings: Settings, args: argparse.Namespace) -> None:
    if args.storage_action in {"archive", "restore"}:
        profile = get_profile(settings, args.profile)
        if not settings.archive_dir:
            raise LabError("Configura LLM_LAB_ARCHIVE_DIR antes de archivar o restaurar", 2)
        active_root = (settings.data_dir / "models").resolve()
        archive_root = (settings.archive_dir / "models").resolve()
        if active_root == archive_root or active_root in archive_root.parents or archive_root in active_root.parents:
            raise LabError("El archivo frío debe estar fuera del directorio de datos activo", 2)
        source_root, destination_root = (
            (active_root, archive_root) if args.storage_action == "archive" else (archive_root, active_root)
        )
        source = source_root / profile["id"]
        destination = destination_root / profile["id"]
        with control_lock(settings):
            if docker_container_running() or read_state(settings):
                raise LabError("Detén el perfil activo antes de mover modelos", 1)
            if not source.is_dir():
                raise LabError(f"No existe el modelo de {profile['id']} en {source_root}", 1)
            if destination.exists():
                raise LabError(f"El destino ya existe: {destination}", 1)
            destination_root.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
        action = "Archivado" if args.storage_action == "archive" else "Restaurado"
        print(f"{action}: {profile['id']} -> {destination}")
        return
    entries = []
    if settings.data_dir.exists():
        for path in sorted(settings.data_dir.iterdir()):
            entries.append({"name": path.name, "path": str(path), "bytes": directory_size(path)})
    archived = []
    if settings.archive_dir and (settings.archive_dir / "models").exists():
        for path in sorted((settings.archive_dir / "models").iterdir()):
            if path.is_dir():
                archived.append({"name": path.name, "path": str(path), "bytes": directory_size(path)})
    payload = {"dataDir": str(settings.data_dir), "archiveDir": str(settings.archive_dir) if settings.archive_dir else None, "totalBytes": sum(item["bytes"] for item in entries), "entries": entries, "archivedModels": archived}
    if args.json:
        print_json(payload)
        return
    print(f"Datos: {payload['dataDir']}")
    for item in entries:
        print(f"{item['bytes'] / 1024**3:8.2f} GiB  {item['name']}")
    print(f"{payload['totalBytes'] / 1024**3:8.2f} GiB  TOTAL")
    if payload["archiveDir"]:
        print(f"Archivo frío: {payload['archiveDir']}")
        for item in archived:
            print(f"{item['bytes'] / 1024**3:8.2f} GiB  {item['name']}")


def command_pull(settings: Settings, args: argparse.Namespace) -> None:
    profile = get_profile(settings, args.profile)
    with control_lock(settings):
        if docker_container_running() or read_state(settings):
            raise LabError("Detén el perfil activo antes de preparar otro", 1)
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        env = compose_env(settings, profile)
        run(compose_command(settings, "build", "server"), cwd=settings.repo_dir, env=env)
        try:
            run(
                compose_command(settings, "run", "--rm", "-e", "LLM_LAB_MODE=pull", "--no-deps", "server"),
                cwd=settings.repo_dir,
                env=env,
            )
        finally:
            run(compose_command(settings, "down", "--remove-orphans"), cwd=settings.repo_dir, env=env, check=False)
    print(f"Runtime y artefactos preparados para {profile['id']}")


def command_benchmark(settings: Settings, args: argparse.Namespace) -> None:
    profile = get_profile(settings, args.profile)
    state = read_state(settings)
    if not state or state.get("state") != "healthy" or state.get("profile") != profile["id"]:
        raise LabError(f"Activa primero el perfil {profile['id']}", 1)
    script = settings.repo_dir / "benchmarks/run.py"
    profile_file = settings.repo_dir / "config" / "profiles" / f"{profile['id']}.json"
    command = [sys.executable, str(script), "--endpoint", settings.endpoint, "--profile", profile["id"], "--profile-file", str(profile_file), "--suite", args.suite]
    if args.repetitions is not None:
        if args.repetitions < 1:
            raise LabError("--repetitions debe ser mayor que cero", 2)
        command.extend(["--repetitions", str(args.repetitions)])
    run(command, cwd=settings.repo_dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llm-lab", description="Plano de control de Local LLM Agent Lab")
    parser.add_argument("--repo-dir", type=pathlib.Path, default=pathlib.Path.cwd(), help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Comprueba requisitos sin modificar el host")
    doctor.add_argument("--json", action="store_true")
    profiles = sub.add_parser("profiles", help="Lista y valida perfiles")
    profiles.add_argument("--json", action="store_true")
    config = sub.add_parser("config", help="Inspecciona configuración")
    config.add_argument("config_action", choices=["show"])
    config.add_argument("--effective", action="store_true")
    start = sub.add_parser("start", help="Inicia un perfil")
    start.add_argument("profile", nargs="?")
    stop = sub.add_parser("stop", help="Detiene el perfil administrado")
    switch = sub.add_parser("switch", help="Cambia de perfil de forma exclusiva")
    switch.add_argument("profile")
    status = sub.add_parser("status", help="Muestra el estado")
    status.add_argument("--json", action="store_true")
    health = sub.add_parser("health", help="Consulta la salud HTTP")
    health.add_argument("--json", action="store_true")
    logs = sub.add_parser("logs", help="Muestra logs del servidor")
    logs.add_argument("--follow", action="store_true")
    logs.add_argument("--tail", type=int, default=200)
    pull = sub.add_parser("pull", help="Prepara el runtime de un perfil")
    pull.add_argument("profile")
    client = sub.add_parser("client-config", help="Genera configuración de cliente")
    client.add_argument("client", choices=["pi", "opencode"])
    client.add_argument("--output", type=pathlib.Path)
    client.add_argument("--force", action="store_true", help="Permite reemplazar --output")
    benchmark = sub.add_parser("benchmark", help="Ejecuta un benchmark")
    benchmark.add_argument("profile")
    benchmark.add_argument("--suite", choices=["smoke", "performance", "agent", "quality", "tools", "context", "soak"], default="smoke")
    benchmark.add_argument("--repetitions", type=int, default=None)
    storage = sub.add_parser("storage", help="Inspecciona almacenamiento persistente")
    storage.add_argument("storage_action", choices=["report", "archive", "restore"])
    storage.add_argument("profile", nargs="?")
    storage.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    commands = {
        "doctor": command_doctor,
        "profiles": command_profiles,
        "config": command_config,
        "start": command_start,
        "stop": command_stop,
        "switch": command_switch,
        "status": command_status,
        "health": command_health,
        "logs": command_logs,
        "pull": command_pull,
        "client-config": command_client_config,
        "benchmark": command_benchmark,
        "storage": command_storage,
    }
    try:
        settings = load_settings(args.repo_dir.resolve())
        commands[args.command](settings, args)
        return 0
    except LabError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("Interrumpido", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

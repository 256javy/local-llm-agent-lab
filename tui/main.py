from __future__ import annotations

import cmd
import json
import os
import subprocess
import sys
import time
import argparse
import colorama
from pathlib import Path

colorama.init(autoreset=True)

from llm_lab import __version__
from llm_lab.core import LabError, Settings, load_settings, load_profiles, gpu_info, docker_container_running, read_state, write_state, clear_state, control_lock, compose_command, compose_env, port_available, http_json, wait_for_health
from llm_lab.cli import state_payload, command_profiles, command_doctor

repo_dir = Path(__file__).resolve().parent.parent

# Colores para la TUI
COLOR_RESET = colorama.Style.RESET_ALL
COLOR_HEALTHY = colorama.Fore.GREEN + colorama.Style.BRIGHT
COLOR_ERROR = colorama.Fore.RED + colorama.Style.BRIGHT
COLOR_WARNING = colorama.Fore.YELLOW + colorama.Style.BRIGHT
COLOR_INFO = colorama.Fore.CYAN
COLOR_PROFILE = colorama.Fore.MAGENTA
COLOR_RESET_LINE = "\033[K"


class Spinner:
    """Spinner simple para operaciones asíncronas"""

    def __init__(self, message: str = "Procesando"):
        self.message = message
        self.frames = ["|", "/", "-", "\\"]
        self.idx = 0
        self._running = False

    def start(self):
        self._running = True
        self.idx = 0

    def stop(self):
        self._running = False
        print(f" {COLOR_RESET}", end="", flush=True)

    def step(self):
        if self._running:
            frame = self.frames[self.idx % len(self.frames)]
            idx_display = (self.idx % len(self.frames))
            self.idx += 1
            print(f"\r {COLOR_INFO}[ {frame} ] {self.message}{COLOR_RESET_LINE}", end="", flush=True)


class LabTUI(cmd.Cmd):
    """TUI interactivo para Local LLM Agent Lab"""

    intro = f"""
    {COLOR_PROFILE}{"=" * 60}{COLOR_RESET}
    {COLOR_PROFILE}Local LLM Agent Lab TUI v{__version__}{COLOR_RESET}
    {COLOR_PROFILE}{"=" * 60}{COLOR_RESET}

    {COLOR_INFO}Comandos:{COLOR_RESET} start <perfil> | stop | status | switch <perfil> | profiles | health | logs | doctor | exit
    """

    prompt = f"{COLOR_INFO}llm-lab{COLOR_RESET} "

    def __init__(self):
        super().__init__()
        self.settings = load_settings(repo_dir)
        self._spinner = Spinner()

    def _print_status_line(self, text: str):
        print(f"{text}{COLOR_RESET_LINE}", flush=True)

    def do_exit(self, arg: str) -> bool:
        """Salir del TUI"""
        self._print_status_line("Saliendo...")
        return True

    def do_quit(self, arg: str) -> bool:
        """Salir del TUI"""
        return self.do_exit(arg)

    def do_EOF(self, arg: str) -> bool:
        """Manejar Ctrl+D para salir"""
        self._print_status_line("\nSaliendo...")
        return True

    def _format_state(self, state: str) -> str:
        """Formatea el estado con color correspondiente"""
        match state.lower():
            case "healthy" | "running":
                return f"{COLOR_HEALTHY}{state.upper()}{COLOR_RESET}"
            case "starting" | "stopping":
                return f"{COLOR_WARNING}{state.upper()}{COLOR_RESET}"
            case "failed" | "error" | "stopped":
                return f"{COLOR_ERROR}{state.upper()}{COLOR_RESET}"
            case _:
                return f"{COLOR_INFO}{state.upper()}{COLOR_RESET}"

    def do_start(self, arg: str) -> None:
        """start [perfil] - Inicia un perfil

        Ejemplo: start gemma-4-12b-qat-mtp
        """
        args = arg.split()
        profile_id = args[0] if args else self.settings.default_profile

        try:
            profiles = load_profiles(self.settings.repo_dir)
            if profile_id not in profiles:
                print(f"Perfil desconocido: {profile_id}", file=sys.stderr)
                return
            profile = profiles[profile_id]
        except LabError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return

        with control_lock(self.settings):
            state = read_state(self.settings)
            if state and state.get("state") != "healthy" and state.get("profile") == profile["id"] and docker_container_running():
                self._spinner.start()
                wait_for_health(self.settings)
                write_state(self.settings, {**state, "state": "healthy"})
                self._spinner.stop()
                print(f"\nPerfil reconciliado: {profile['id']} en {self.settings.endpoint}\n")
                return
            if state and state.get("state") == "healthy" and docker_container_running():
                if state.get("profile") == profile["id"]:
                    print(f"\nEl perfil {profile['id']} ya está activo en {self.settings.endpoint}\n")
                    return
                raise LabError(f"Ya está activo {state.get('profile')}; usa `switch {profile['id']}`", 1)
            env = compose_env(self.settings, profile)
            if not port_available(self.settings.host, self.settings.port):
                raise LabError(f"El puerto {self.settings.host}:{self.settings.port} está ocupado", 4)
            gpu = gpu_info()
            baseline = gpu["vramUsedMiB"] if gpu else None
            state_base = {
                "profile": profile["id"],
                "endpoint": self.settings.endpoint,
                "runtime": profile["runtime"]["adapter"],
                "startedAt": time.time(),
                "vramBaselineMiB": baseline,
            }
            write_state(self.settings, {"state": "starting", **state_base})
            self._spinner.start()
            try:
                subprocess.run(
                    compose_command(self.settings, "up", "-d", "--build", "server"),
                    cwd=self.settings.repo_dir,
                    env=env,
                    check=False,
                )
                wait_for_health(self.settings)
            except Exception:
                write_state(self.settings, {"state": "failed", **state_base})
                self._spinner.stop()
                raise
            write_state(self.settings, {"state": "healthy", **state_base})
            self._spinner.stop()
        print(f"\nPerfil activo: {profile['id']} en {self.settings.endpoint}\n")

    def do_stop(self, arg: str) -> None:
        """stop - Detiene el perfil administrado"""
        try:
            with control_lock(self.settings):
                state = read_state(self.settings)
                profile = None
                if state and state.get("profile"):
                    try:
                        from llm_lab.core import get_profile
                        profile = get_profile(self.settings, state["profile"])
                    except LabError:
                        profile = None
                if not docker_container_running() and not state:
                    self._print_status_line("No hay un perfil administrado activo")
                    return
                previous_state = dict(state or {})
                env = os.environ.copy()
                env.update(
                    {
                        "LLM_LAB_HOST": self.settings.host,
                        "LLM_LAB_PORT": str(self.settings.port),
                        "LLM_LAB_DATA_DIR": str(self.settings.data_dir),
                        "LLM_LAB_PROFILE_FILE": (state or {}).get("_path", ""),
                        "LLM_LAB_API_KEY": self.settings.api_key,
                    }
                )
                self._spinner.start()
                subprocess.run(
                    compose_command(self.settings, "down", "--remove-orphans", "--timeout", str(self.settings.stop_timeout)),
                    cwd=self.settings.repo_dir,
                    env=env,
                    check=False,
                )
                deadline = time.monotonic() + self.settings.stop_timeout
                while docker_container_running() and time.monotonic() < deadline:
                    self._spinner.step()
                    time.sleep(1)
                if docker_container_running():
                    self._spinner.stop()
                    raise LabError("El contenedor administrado no se detuvo; no se iniciará otro perfil", 7)
                baseline = previous_state.get("vramBaselineMiB")
                if isinstance(baseline, int):
                    deadline = time.monotonic() + self.settings.stop_timeout
                    while time.monotonic() < deadline:
                        gpu = gpu_info()
                        if gpu is None or gpu["vramUsedMiB"] <= baseline + 512:
                            break
                        self._spinner.step()
                        time.sleep(1)
                    else:
                        self._spinner.stop()
                        raise LabError(
                            f"La VRAM no volvió al nivel previo: se esperaban como máximo {baseline + 512} MiB",
                            7,
                        )
                clear_state(self.settings)
                self._spinner.stop()
            self._print_status_line("Servidor detenido; modelos y caches fueron preservados")
        except LabError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)

    def do_switch(self, arg: str) -> None:
        """switch <perfil> - Cambia de perfil de forma exclusiva"""
        profile_id = arg.strip() if arg.strip() else self.settings.default_profile
        try:
            from llm_lab.core import get_profile
            profile = get_profile(self.settings, profile_id)
        except LabError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return

        with control_lock(self.settings):
            state = read_state(self.settings)
            current = get_profile(self.settings, state["profile"]) if state and state.get("profile") in load_profiles(self.settings.repo_dir) else None
            if state or docker_container_running():
                env = os.environ.copy()
                env.update(
                    {
                        "LLM_LAB_HOST": self.settings.host,
                        "LLM_LAB_PORT": str(self.settings.port),
                        "LLM_LAB_DATA_DIR": str(self.settings.data_dir),
                        "LLM_LAB_API_KEY": self.settings.api_key,
                    }
                )
                self._spinner.start()
                subprocess.run(
                    compose_command(self.settings, "down", "--remove-orphans"),
                    cwd=self.settings.repo_dir,
                    env=env,
                    check=False,
                )
            if not port_available(self.settings.host, self.settings.port):
                self._spinner.stop()
                raise LabError(f"El puerto {self.settings.host}:{self.settings.port} sigue ocupado por un proceso externo", 4)
            env = compose_env(self.settings, profile)
            self._spinner.start()
            subprocess.run(
                compose_command(self.settings, "up", "-d", "--build", "server"),
                cwd=self.settings.repo_dir,
                env=env,
                check=False,
            )
            wait_for_health(self.settings)
            self._spinner.stop()
        print(f"\nPerfil activo: {profile['id']} en {self.settings.endpoint}\n")

    def do_status(self, arg: str) -> None:
        """status - Muestra el estado actual"""
        payload = state_payload(self.settings)
        state = payload.get("state", "unknown")
        state_display = self._format_state(state)

        lines = [
            f"{COLOR_PROFILE}Estado:{COLOR_RESET} {state_display}",
            f"{COLOR_PROFILE}Perfil:{COLOR_RESET} {payload.get('profile', '—')}",
            f"{COLOR_PROFILE}Endpoint:{COLOR_RESET} {payload.get('endpoint', self.settings.endpoint)}",
            f"{COLOR_PROFILE}Contenedor activo:{COLOR_RESET} {'sí' if payload.get('containerRunning') else 'no'}",
        ]
        if payload.get("gpu"):
            gpu = payload["gpu"]
            gpu_line = f"{COLOR_PROFILE}GPU:{COLOR_RESET} {gpu['name']} — {gpu['vramUsedMiB']}/{gpu['vramTotalMiB']} MiB"
            lines.append(gpu_line)

        self._print_status_line("\n".join(lines))

    def do_profiles(self, arg: str) -> None:
        """profiles - Lista los perfiles disponibles"""
        command_profiles(self.settings, argparse.Namespace(json=False))

    def do_health(self, arg: str) -> None:
        """health - Consulta la salud HTTP"""
        try:
            code, payload = http_json(f"http://{self.settings.host}:{self.settings.port}/health", self.settings.api_key)
            result = {"ok": code == 200, "statusCode": code, "payload": payload, "endpoint": self.settings.endpoint}
            ok_str = "OK" if result["ok"] else "ERROR"
            self._print_status_line(f"{COLOR_PROFILE}{ok_str}: HTTP {code}: {payload}{COLOR_RESET}")
            if code != 200:
                raise LabError("Servidor no saludable", 6)
        except LabError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)

    def do_logs(self, arg: str) -> None:
        """logs [--tail N] - Muestra logs del servidor"""
        tails = arg.split() if arg else []
        tail_val = 200
        for i, t in enumerate(tails):
            if t.startswith("--tail="):
                tail_val = int(t.split("=")[1])
            elif t.startswith("--tail"):
                if i + 1 < len(tails):
                    tail_val = int(tails[i + 1])
        command = compose_command(self.settings, "logs", "--tail", str(tail_val))
        command.append("server")
        subprocess.run(command, cwd=self.settings.repo_dir, check=False)

    def do_doctor(self, arg: str) -> None:
        """doctor - Ejecuta diagnóstico de requisitos"""
        try:
            command_doctor(self.settings, argparse.Namespace(json=False))
        except LabError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)

    def emptyline(self) -> None:
        """Línea vacía no hace nada"""
        pass

    def default(self, line: str) -> None:
        """Comando por defecto - muestra ayuda"""
        if line.strip():
            print(f"Comando no reconocido: {line}".strip())
        print("Escribe 'help' o '?' para ver los comandos disponibles")

    def postcmd(self, stop, line) -> None:
        """After each command, print a newline for readability"""
        if not stop:
            print()
        return stop


def main() -> int:
    tui = LabTUI()
    try:
        tui.cmdloop()
    except KeyboardInterrupt:
        print(f"\n{COLOR_ERROR}Interrumpido{COLOR_RESET}")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

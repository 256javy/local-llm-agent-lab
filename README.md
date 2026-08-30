# Local LLM Agent Lab

Runtime local y extensible para ejecutar un único LLM a la vez en Docker y
consumirlo desde agentes instalados en el host, como Pi Coding Agent y OpenCode.

El endpoint predeterminado es:

```text
http://127.0.0.1:18080/v1
```

La configuración de referencia es una NVIDIA RTX 5060 Ti de 16 GB. Otras GPU
NVIDIA con 16 GB pueden reutilizar los perfiles, pero deben ajustar la
arquitectura CUDA si no son Blackwell: el perfil de referencia se compila para
`sm_120` y puede sobrescribirse con `LLM_LAB_CUDA_ARCHITECTURES`. Tener la misma VRAM no garantiza el mismo rendimiento ni soporte de
instrucciones; ejecuta `doctor`, build y la matriz de benchmarks antes de
considerar un perfil validado en otro equipo.

## Estado

El runtime está implementado y validado en una RTX 5060 Ti de 16 GB con Gemma
4 12B, Qwen 3.6 35B-A3B y Qwen 3.8 27B. Consulta la [documentación](docs/README.md) para la
arquitectura, operación, validación y extensiones pendientes.

## Inicio rápido

```bash
cp .env.example .env
./bin/llm-lab doctor
./bin/llm-lab profiles
./bin/llm-lab start gemma-4-12b-qat-mtp
./bin/llm-lab health
```

Cambiar de modelo libera primero el perfil activo:

```bash
./bin/llm-lab switch qwen-3.6-moe-2bit
./bin/llm-lab status
./bin/llm-lab stop
```

`stop` no borra modelos ni caches.

## TUI

La TUI predeterminada (`tui/`, Rust + ratatui) comparte el contrato operativo
de `bin/llm-lab`:

- `start` / `stop` / `switch <perfil>`
- `status`, `health`, `profiles`, `doctor`
- `logs` (`--tail`, `--follow`)
- marcado del perfil por defecto

Usa el mismo lock de control sobre `state.json`, por lo que puede alternarse
con la CLI sin corromper el estado. Mantiene la telemetría a la izquierda y
usa el panel derecho para alternar entre perfiles, logs y resultados de
operaciones sin ocultar el dashboard.

```bash
./tui/run_tui.sh  # compila en el primer uso
```

## Clientes

La CLI genera configuraciones sin sobrescribir archivos existentes:

```bash
./bin/llm-lab client-config pi
./bin/llm-lab client-config opencode
```

Para escribir en una ruta nueva de forma explícita:

```bash
./bin/llm-lab client-config pi --output /tmp/models.json
```

La CLI se niega a reemplazar archivos salvo que se use `--force`; en ese caso
crea antes un backup `archivo.bak-YYYY-MM-DD`.

Pi y OpenCode deben ejecutarse desde el directorio del proyecto sobre el que
trabajarán. La inferencia permanece aislada en Docker.

OpenCode ya está soportado mediante `@ai-sdk/openai-compatible`. Para Pi se
requiere su instalación en el host:

```bash
npm install -g @mariozechner/pi-coding-agent
./bin/llm-lab client-config pi --output ~/.pi/agent/models.json
```

Si el archivo ya existe, genera primero la configuración sin `--output` y
combina el proveedor `local-lab`; no fuerces un reemplazo sin revisar el backup.

## Validación rápida

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
docker compose config --quiet
./bin/llm-lab config show --effective
```

## Datos locales

Por defecto, modelos, fuentes y caches se guardan bajo
`~/.local/share/local-llm-agent-lab`. Define `LLM_LAB_DATA_DIR` para cambiarlo.
Estos artefactos nunca se versionan.

```bash
./bin/llm-lab storage report
```

Los modelos de uso ocasional pueden archivarse en otro disco sin cambiar sus
perfiles. Configura `LLM_LAB_ARCHIVE_DIR` y usa:

```bash
./bin/llm-lab storage archive qwen-3.8-27b-iq3xxs-mtp
./bin/llm-lab storage restore qwen-3.8-27b-iq3xxs-mtp
```

El proyecto se distribuye bajo licencia [MIT](LICENSE). Las dependencias,
runtimes y modelos conservan sus propias licencias; consulta
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

# Local LLM Agent Lab

Runtime local y extensible para ejecutar un único LLM a la vez en Docker y
consumirlo desde agentes instalados en el host, como Pi Coding Agent y OpenCode.

El endpoint predeterminado es:

```text
http://127.0.0.1:18080/v1
```

## Estado

El MVP está implementado y validado en una RTX 5060 Ti de 16 GB con Gemma 4
12B y Qwen 3.6 35B-A3B. Consulta [`docs/VALIDATION.md`](docs/VALIDATION.md) para
la evidencia y [`docs/BACKLOG.md`](docs/BACKLOG.md) para las extensiones
pendientes. El alcance completo está definido en
[`PRD_LOCAL_LLM_AGENT_LAB.md`](PRD_LOCAL_LLM_AGENT_LAB.md).

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

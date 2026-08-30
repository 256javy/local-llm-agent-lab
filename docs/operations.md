# Operación

## Preflight

```bash
./bin/llm-lab doctor
./bin/llm-lab config show --effective
```

`doctor` no cambia el host. Comprueba perfiles, herramientas, daemon Docker,
GPU, puerto y almacenamiento.

## Ciclo de vida

```bash
./bin/llm-lab start gemma-4-12b-qat-mtp
./bin/llm-lab status
./bin/llm-lab health
./bin/llm-lab switch qwen-3.6-moe-2bit
./bin/llm-lab stop
```

La primera construcción compila la revisión fijada de llama.cpp y el primer
inicio puede descargar varios GiB. Los perfiles comparten una revisión que
soporta sus contratos MTP y se compila de forma nativa para `sm_120`. `stop` y
`switch` preservan la cache y verifican que la VRAM vuelva cerca del nivel
previo antes de continuar.

## Conflictos

Si el puerto 18080 está ocupado, la CLI falla antes de iniciar Docker. Cambia
`LLM_LAB_PORT` en `.env` o detén el proceso externo. La CLI no termina procesos
ajenos.

Si otro proceso usa VRAM, `doctor` lo refleja mediante el uso global. El MVP no
termina procesos GPU ni garantiza que el modelo quepa si existe otra carga.

## TUI

Existen dos TUI equivalentes:

- `tui/main.py` (Python + cmd) — clásica.
- `tui-v2/` (Rust + ratatui) — reimplementa la misma lógica con mejor
  feedback visual: telemetría persistente a la izquierda y un panel derecho
  que alterna entre perfiles, operaciones y logs en vivo, con spinner y
  footer contextual.

Ambas comparten el lock sobre `state.json` con la CLI, por lo que es
seguro alternar. Para arrancarlas:

```bash
./tui/run_tui.sh
./tui-v2/run_tui.sh
```

Teclas comunes en la TUI Rust: `↑/↓` navega, `Enter` arranca, `s` cambia,
`x` detiene, `d` marca como default, `r` refresca, `h` health, `l` logs,
`L` logs en vivo, `D` doctor, `?` ayuda, `q` salir. Las acciones
destructivas muestran un diálogo de confirmación.

## Datos

El directorio predeterminado es `~/.local/share/local-llm-agent-lab`. Para
inspeccionar tamaños:

```bash
./bin/llm-lab storage report
```

No borres volúmenes o caches como parte de una recuperación ordinaria.
Reconstruir la imagen para actualizar CUDA o llama.cpp tampoco borra esos
artefactos: si el perfil conserva el mismo identificador y nombre de archivo,
el entrypoint reutiliza el GGUF existente bajo `models/<perfil>/`.

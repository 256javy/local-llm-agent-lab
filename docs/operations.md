# Operación

## Preflight

```bash
./bin/llm-lab doctor
./bin/llm-lab config show --effective
```

`doctor` no cambia el host. Comprueba perfiles, herramientas, daemon Docker,
GPU, puerto y almacenamiento.

Los perfiles fijan `sm_120` para la RTX 5060 Ti. En otra GPU NVIDIA determina
primero su compute capability y configura, por ejemplo,
`LLM_LAB_CUDA_ARCHITECTURES=89`; el siguiente build recompilará llama.cpp para
ese target. No copies `120` solo por tener 16 GB de VRAM.

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

La TUI predeterminada vive en `tui/` y usa Rust con ratatui. Comparte el lock
sobre `state.json` con la CLI, por lo que es seguro alternarlas. Mantiene la
telemetría persistente a la izquierda y un panel derecho que alterna entre
perfiles, operaciones y logs en vivo, con spinner y footer contextual.

Para arrancarla:

```bash
./tui/run_tui.sh
```

Teclas: `↑/↓` navega, `Enter` arranca, `s` cambia,
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

Después de un upgrade, verifica la imagen concreta de cada perfil antes de
atribuirle resultados al nuevo stack. Las etiquetas son independientes y un
perfil que no se haya reconstruido puede seguir apuntando a una imagen previa:

```bash
docker image inspect local/local-llm-agent-lab:<perfil> \
  --format '{{range .Config.Env}}{{println .}}{{end}}' | grep '^CUDA_VERSION='
```

El `system_fingerprint` de las respuestas y los logs de arranque permiten
corroborar también la revisión efectiva de llama.cpp.

## Archivo frío en otro disco

`LLM_LAB_DATA_DIR` contiene los modelos activos. `LLM_LAB_ARCHIVE_DIR` puede
apuntar a un HDD para conservar modelos de uso ocasional sin mantenerlos en el
SSD. En el equipo de referencia puede configurarse, por ejemplo:

```bash
LLM_LAB_ARCHIVE_DIR=/mnt/storage-lv/local-llm-agent-lab-archive
```

Con el servidor detenido:

```bash
./bin/llm-lab storage archive qwen-3.8-27b-iq3xxs-mtp
./bin/llm-lab storage report
./bin/llm-lab storage restore qwen-3.8-27b-iq3xxs-mtp
```

## Benchmark nativo

Detén el servidor antes de ejecutar la matriz reproducible de `llama-bench`:

```bash
./bin/llm-lab stop
./bin/llm-lab bench gemma-4-12b-qat-mtp
```

El benchmark usa exclusivamente el modelo ya preparado bajo
`LLM_LAB_DATA_DIR`, no publica puertos y deja el servidor detenido al finalizar.
Los resultados locales quedan ignorados por Git bajo
`benchmark-results/llama-bench/`. Consulta [Benchmarking](benchmarking.md) para
la matriz, reanudación y opciones.

Las operaciones mueven el directorio completo del perfil, funcionan entre
filesystems y se niegan a sobrescribir un destino existente. `start` no restaura
automáticamente un modelo archivado: esa separación evita copias grandes por
accidente. El cache de Hugging Face permanece en el almacenamiento activo.

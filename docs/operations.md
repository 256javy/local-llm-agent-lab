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

La primera construcción puede compilar llama.cpp y el primer inicio puede
descargar varios GiB. Qwen y Gemma fijan revisiones distintas porque sus
formatos MTP tienen contratos diferentes. `stop` y `switch` preservan la cache
y verifican que la VRAM vuelva cerca del nivel previo antes de continuar.

## Conflictos

Si el puerto 18080 está ocupado, la CLI falla antes de iniciar Docker. Cambia
`LLM_LAB_PORT` en `.env` o detén el proceso externo. La CLI no termina procesos
ajenos.

Si otro proceso usa VRAM, `doctor` lo refleja mediante el uso global. El MVP no
termina procesos GPU ni garantiza que el modelo quepa si existe otra carga.

## Datos

El directorio predeterminado es `~/.local/share/local-llm-agent-lab`. Para
inspeccionar tamaños:

```bash
./bin/llm-lab storage report
```

No borres volúmenes o caches como parte de una recuperación ordinaria.

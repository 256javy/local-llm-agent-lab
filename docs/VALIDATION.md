# Validación local

Fecha: 2026-08-02. Hardware: NVIDIA GeForce RTX 5060 Ti de 16 GB, compute
capability 12.0, driver 580.173.02.

## Resultado

- `doctor`: Docker, Compose, GPU, herramientas, puerto 18080 y disco correctos.
- Gemma 4 12B QAT + MTP: saludable, API OpenAI, tool call y performance.
- Qwen 3.6 35B-A3B Q2 + MTP: saludable, API OpenAI, tool call y performance.
- Ciclo Qwen → Gemma → Qwen: saludable y sin coexistencia de modelos.
- OpenCode 1.17.11: chat `OK` desde `/tmp` con configuración temporal.
- Pi: plantilla generada y validada como JSON; ejecución pendiente porque el
  binario no está instalado en este host.
- 13 pruebas unitarias: correctas.

## Presupuesto observado

| Perfil | Contexto | VRAM saludable | Decode medio | Smoke máximo mediano |
|---|---:|---:|---:|---:|
| Gemma 4 12B QAT + MTP | 65.536 | 9.013 MiB | 94,34 tok/s | 0,670 s |
| Qwen 3.6 35B-A3B Q2 + MTP | 32.768 | 14.878 MiB | 104,06 tok/s | 0,707 s |

La tarea corta de performance midió 125,17 tok/s para Gemma y 149,14 tok/s
para Qwen. No debe extrapolarse a contextos largos. Los JSON completos quedan
en `benchmark-results/`, ignorados por Git.

## MTP observado

Los logs reportaron drafts aceptados en ambos perfiles. En las repeticiones de
smoke, Gemma aceptó 132 de 156 tokens draft acumulados y Qwen 217 de 231. Estos
datos prueban que MTP está activo, pero todavía no seleccionan el valor óptimo;
el barrido de `spec-draft-n-max` permanece en backlog.

## Liberación y persistencia

Gemma bajó de aproximadamente 9.017 MiB a 951 MiB después de `stop`. El ciclo
de cambio partió de un baseline cercano a 947 MiB antes de cada carga. Los
artefactos persistieron bajo `~/.local/share/local-llm-agent-lab`; el reporte
final fue de 19,62 GiB.

## Revisiones relevantes

- Gemma: llama.cpp `0ab9d6fed73dbc5dc8026c868cb10a6728c4ed48`.
- Qwen: head MTP `2dff7ff8f90ce6daefd6adb097d58a4276e5dd2d`.
- Los builds usan CUDA 12.8.1 y `CMAKE_CUDA_ARCHITECTURES=120`.

Qwen requiere desactivar tanto `LLAMA_BUILD_WEBUI` como `LLAMA_BUILD_UI` por
compatibilidad con esa revisión. Su GGUF contiene los heads MTP; no usa el
archivo draft externo empleado por Gemma.

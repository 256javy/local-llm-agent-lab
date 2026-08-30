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
- Los builds validados en esta sesión usaron CUDA 12.8.1 y
  `CMAKE_CUDA_ARCHITECTURES=120`.

Qwen requiere desactivar tanto `LLAMA_BUILD_WEBUI` como `LLAMA_BUILD_UI` por
compatibilidad con esa revisión. Su GGUF contiene los heads MTP; no usa el
archivo draft externo empleado por Gemma.

## Upgrade CUDA 13 y llama.cpp

El runtime vigente fija CUDA 13.0.3 y llama.cpp `b10689`, revisión
`57291f2644af8c9df0dd8d44395881c5bdcf0ecd`, para los cuatro perfiles. Se mantiene
`CMAKE_CUDA_ARCHITECTURES=120`; Qwen conserva `draft-mtp` con el MTP embebido y
Gemma conserva su modelo draft separado. La UI embebida y su descarga mutable
están deshabilitadas porque el servidor solo publica la API local. Los
resultados de la sección anterior son el baseline de CUDA 12.8.1 y no deben
atribuirse al runtime actualizado sin repetir smoke, VRAM, tool calling y
performance.

Validación del 2026-08-30 sobre la misma RTX 5060 Ti y driver 580.173.02:

- Build correcto con toolkit CUDA 13.0.88 y target efectivo `sm_120a`; no se
  observó el warning de targets GPU anteriores a `sm_75`.
- Las instancias CUDA `mxfp4` y `nvfp4` compilaron correctamente.
- Gemma 12B y Qwen 3.6 pasaron health, smoke, tool calling y performance; MTP
  quedó activo en ambos.
- Los GGUF existentes se reutilizaron desde el volumen persistente, sin nuevas
  descargas de modelos.
- El mismo build de llama.cpp se reutilizó íntegramente entre perfiles.

| Perfil | VRAM observada | Decode mediano corto | Aceptación draft acumulada |
|---|---:|---:|---:|
| Gemma 4 12B QAT + MTP | 9.039 MiB | 123,25 tok/s | 48/48 |
| Qwen 3.6 35B-A3B Q2 + MTP | 14.137 MiB | 196,40 tok/s | 39/45 |
| Qwen 3.8 27B IQ3_XXS + MTP | 13.063 MiB | 59,95 tok/s | 33/36 |

Estas cifras proceden del fixture corto `performance`, con cache de prompt en
las repeticiones, y no sustituyen un benchmark de contexto largo. El
2026-08-30 se repitieron además `smoke`, `performance` y `agent` para los tres
modelos descargados: las nueve suites pasaron y las respuestas reportaron
`system_fingerprint: b1-57291f2`. Las tres imágenes declararon
`CUDA_VERSION=13.0.3`; al terminar, el servidor quedó detenido y la VRAM volvió
a 968 MiB. Gemma 26B no está descargado y conserva pendiente su validación
pesada para evitar una descarga implícita de varios GiB.

## Baseline adicional de Qwen 3.8 sobre el stack anterior

Qwen 3.8 27B IQ3_XXS se descargó y pasó las suites `smoke`, `performance` y
`agent` el 2026-08-30, reutilizando accidentalmente una imagen construida con
CUDA 12.8.1 y la revisión anterior de llama.cpp `093adb2`. El resultado es útil
como baseline de compatibilidad del modelo y confirma chat, tool calling y MTP,
pero no valida el runtime declarado actualmente por el perfil.

La ejecución observó 13.176 MiB de VRAM, 56,54 tok/s de decode mediano en el
fixture corto de performance y 11/12 tokens draft aceptados en cada repetición.
La respuesta del servidor expuso `system_fingerprint: b1-093adb2`; además, la
imagen utilizada declaró `CUDA_VERSION=12.8.1`. Estas evidencias prevalecen
sobre la revisión copiada del archivo de perfil al JSON del benchmark.

Este baseline se conserva para comparar compatibilidad y rendimiento. Qwen 3.8
fue reconstruido después con el runtime vigente y sus resultados CUDA 13 se
incorporaron a la tabla anterior. Gemma 26B sigue siendo el único GGUF del
catálogo que no está descargado.

## Suites ampliadas

El 2026-08-30 Gemma 4 12B validó el primer corte de las suites nuevas sobre
CUDA 13.0.3 y `b1-57291f2`:

| Suite | Casos por fixture | Máximo mediano | Máximo p95 | Resultado |
|---|---:|---:|---:|---|
| `quality` | 3 | 0,131 s | 0,171 s | correcto |
| `tools` | 3 | 1,072 s | 1,123 s | correcto |
| `context` (~8K) | 3 | 0,233 s | 3,864 s | correcto |
| `soak` | 50 | 0,659 s | 0,669 s | correcto |

`soak` ejecutó dos fixtures, por lo que completó 100 solicitudes sin fallos.
El p95 de contexto incluye la primera evaluación en frío y evidencia por qué se
registran percentiles además de la mediana. Falta ejecutar esta matriz sobre los
otros perfiles y sumar los benchmarks externos versionados indicados en el
backlog.

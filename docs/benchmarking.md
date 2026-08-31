# Benchmarking

## Tres capas que no se mezclan

- `llm-lab bench <perfil>` ejecuta `llama-bench` dentro del runtime: mide
  inferencia nativa, no calidad ni speculative decoding del servidor.
- `llm-lab benchmark <perfil> --suite ...` usa `llama-server` por HTTP y mide
  fixtures controlados del perfil servido.
- `llm-lab trace ...` analizará sesiones reales de Pi/OpenCode, sus herramientas,
  contexto, verificación e intervención humana.

Un resultado de una capa no sustituye a los otros dos.

Con un perfil saludable:

```bash
./bin/llm-lab benchmark gemma-4-12b-qat-mtp --suite smoke
```

Los resultados se guardan como JSON ignorado por Git en
`benchmark-results/`. Cada registro incluye plataforma, GPU, revisiones de
runtime/modelo, argumentos efectivos, fixture, aserciones, duraciones, timings
del servidor y respuestas completas para auditoría funcional. El comando falla
si una respuesta no satisface su aserción.

La revisión de runtime del JSON procede del perfil declarativo. Para auditar un
upgrade de la imagen también se debe comprobar la variable `CUDA_VERSION` de la
imagen y el `system_fingerprint` devuelto por el servidor; una etiqueta Docker
existente puede conservar un build anterior aunque el perfil ya apunte a otra
revisión.

Suites disponibles:

- `smoke`: chat exacto y llamada de herramienta.
- `agent`: llamada de herramienta aislada.
- `performance`: generación corta de código con timings de prompt/decode.
- `quality`: aritmética, seguimiento estricto de instrucciones y español.
- `tools`: selección entre herramientas y decisión correcta de no invocarlas.
- `context`: recuperación determinista dentro de aproximadamente 8K tokens.
- `soak`: smoke y tool calling repetidos 50 veces por defecto.

La cantidad de repeticiones puede ajustarse:

```bash
./bin/llm-lab benchmark <perfil> --suite quality --repetitions 5
./bin/llm-lab benchmark <perfil> --suite soak --repetitions 100
```

Cada registro incluye mediana y p95, snapshot de GPU, ID y fecha de la imagen,
`CUDA_VERSION`, fingerprint del servidor, timings y aceptación MTP. Estas suites
son gates operativos del proyecto; no reemplazan benchmarks académicos.

## Comparaciones estándar

- `llama-bench` se compila junto a `llama-server`, reutiliza el GGUF ya
  preparado y guarda su JSON raw bajo `benchmark-results/llama-bench/`.
  La matriz central es `pp512`, `pp2048`, `pp8192`, `tg128`, `tg512` y
  `tg128` con depth 8192/16384, cinco repeticiones y recorte por el
  `server.contextSize` del perfil.
- La salida estructurada upstream contiene commit/build, CPU/GPU/backends,
  metadata del modelo, batch/ubatch, KV, GPU layers, flash attention, prompt,
  generation, depth, timestamps, media y desviación. El manifest local añade
  profile ID y hash del GGUF. No se parsea la tabla Markdown: siempre se usa
  `-o json`.
- Solo se traducen argumentos compatibles (`ngl`, `fa`, `ctk`, `ctv`, `sm`,
  `mg` y mmap si aplica). Sampling, Jinja, `--spec-type draft-mtp` y
  `--spec-draft-n-max` son del servidor y no aparecen como rendimiento
  MTP de `llama-bench`.
- Una ejecución normal con warmup, `--no-warmup` y el arranque frío externo de
  proceso/modelo son mediciones diferentes. Esta integración no mide cold
  start.

Con el servidor detenido y el runtime del perfil ya construido:

```bash
./bin/llm-lab bench gemma-4-12b-qat-mtp
```

El comando toma el lock de control y rechaza cualquier contenedor administrado
activo. Nunca descarga modelos: si falta el GGUF indica el comando `pull`
correspondiente. La matriz versionada está en `benchmarks/native-matrix.json` y
puede seleccionarse explícitamente con `--matrix standard`.

Cada caso se guarda de forma atómica en un JSON independiente. Repetir el mismo
perfil, matriz, cantidad de repeticiones y modo de warmup reanuda los casos ya
válidos. El directorio de la ejecución contiene además `manifest.json`, con la
revisión, hash del modelo, traducción de argumentos y resultados, y
`summary.md`, con una tabla legible. Para una ruta local distinta:

```bash
./bin/llm-lab bench qwen-3.6-moe-2bit --output /ruta/resultados
```

`--repetitions` permite una corrida diagnóstica más corta. `--no-warmup` crea
otra ejecución y no se presenta como cold start. Sampling, Jinja y MTP quedan
registrados como argumentos ignorados; `mtpMeasured` siempre es `false` en el
manifest nativo.

### Baseline nativo (2026-08-31)

Matriz `standard`, cinco repeticiones, RTX 5060 Ti 16 GB, revisión de runtime
b10689. Valores en tokens/s promedio; los JSON crudos quedan fuera de Git bajo
`benchmark-results/llama-bench/`.

| Caso | gemma-4-12b-qat-mtp | qwen-3.6-moe-2bit | qwen-3.8-27b-iq3xxs-mtp |
| --- | ---: | ---: | ---: |
| pp512 | 2328.30 | 2278.32 | 922.61 |
| pp2048 | 2357.90 | 2341.50 | 921.20 |
| pp8192 | 2220.27 | 2230.87 | 892.10 |
| tg128 | 54.14 | 117.53 | 32.10 |
| tg512 | 52.94 | 115.63 | 32.03 |
| tg128-d8192 | 50.16 | 107.86 | 30.24 |
| tg128-d16384 | 48.10 | 99.88 | 28.53 |

MTP no está medido en ninguna de estas cifras: `llama-bench` no ejecuta el
decodificador especulativo del perfil y el manifest lo refleja con
`mtpMeasured: false`.

Referencia de viabilidad: la
[documentación oficial de llama-bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md)
documenta JSON/JSONL, cinco repeticiones predeterminadas, depth, tipos KV,
flash attention y la metadata anterior. La traducción de flags está validada
contra la revisión fijada b10689; upstream puede cambiarlos en revisiones
posteriores.
- Usa `lm-evaluation-harness` contra el endpoint OpenAI-compatible para IFEval,
  GSM8K, ARC Challenge y una muestra fijada de MMLU-Pro.
- Usa BFCL para tool calling y HumanEval+/MBPP+ para código ejecutable.
- Trata SWE-bench como evaluación del sistema agente completo, no como métrica
  aislada del modelo.

Las versiones, datasets, seeds, límites de muestras, prompts y resultados deben
quedar fijados antes de publicar comparaciones. Los benchmarks largos no forman
parte de la validación rápida ni deben descargar dependencias implícitamente.

Las comparaciones entre runtimes deben usar el mismo modelo, cuantización,
contexto, sampling y fixtures. Las comparaciones entre perfiles representan la
experiencia completa y no aíslan el costo del runtime.

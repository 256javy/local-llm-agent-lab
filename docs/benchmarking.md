# Benchmarking

## Tres capas que no se mezclan

- `llm-lab bench <perfil>` ejecutará `llama-bench` dentro del runtime: mide
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

- `llama-bench` debe compilarse junto a `llama-server`, reutilizar el GGUF ya
  preparado y guardar su JSON raw bajo `benchmark-results/llama-bench/`.
  La matriz central es `pp512`, `pp2048`, `pp8192`, `tg128`, `tg512` y
  `tg128` con depth 8192/16384, cinco repeticiones y recorte por el
  `server.contextSize` del perfil.
- La salida estructurada upstream contiene commit/build, CPU/GPU/backends,
  metadata del modelo, batch/ubatch, KV, GPU layers, flash attention, prompt,
  generation, depth, timestamps, media y desviación. El manifest local añadirá
  profile ID y hash del GGUF cuando calcularlo sea razonable. No se parseará la
  tabla Markdown si `-o json` está disponible.
- Solo se traducen argumentos compatibles (`ngl`, `fa`, `ctk`, `ctv`, `sm`,
  `mg` y mmap si aplica). Sampling, Jinja, `--spec-type draft-mtp` y
  `--spec-draft-n-max` son del servidor y no deben aparecer como rendimiento
  MTP de `llama-bench`.
- Una ejecución normal con warmup, `--no-warmup` y el arranque frío externo de
  proceso/modelo son mediciones diferentes. La primera integración no necesita
  medir cold start.

Referencia de viabilidad: la
[documentación oficial de llama-bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md)
documenta JSON/JSONL, cinco repeticiones predeterminadas, depth, tipos KV,
flash attention y la metadata anterior. Antes de implementar se debe comprobar
la ayuda de la revisión fijada b10689, porque upstream puede cambiar flags.
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

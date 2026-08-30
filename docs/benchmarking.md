# Benchmarking

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

- Usa `llama-bench` de la misma revisión fijada de llama.cpp para prompt
  processing y generación pura con `pp512`, `pp2048`, `pp8192`, `tg128` y
  `tg512`, tanto en frío como en caliente.
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

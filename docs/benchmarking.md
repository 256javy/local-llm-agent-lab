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

Las comparaciones entre runtimes deben usar el mismo modelo, cuantización,
contexto, sampling y fixtures. Las comparaciones entre perfiles representan la
experiencia completa y no aíslan el costo del runtime.

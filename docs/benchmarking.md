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

Suites disponibles:

- `smoke`: chat exacto y llamada de herramienta.
- `agent`: llamada de herramienta aislada.
- `performance`: generación corta de código con timings de prompt/decode.

Las comparaciones entre runtimes deben usar el mismo modelo, cuantización,
contexto, sampling y fixtures. Las comparaciones entre perfiles representan la
experiencia completa y no aíslan el costo del runtime.

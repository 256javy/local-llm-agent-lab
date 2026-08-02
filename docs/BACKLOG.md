# Backlog vivo

## Convenciones

- `[x]` implementado y validado.
- `[~]` implementado, pendiente de validación pesada o con GPU.
- `[ ]` pendiente.

## Fase 0 — Bootstrap

- [x] Crear repositorio y mover el PRD.
- [x] Añadir README, AGENTS.md, licencia y `.gitignore`.
- [x] Definir esquema y registro inicial de perfiles.
- [x] Implementar CLI y pruebas sin GPU.
- [x] Crear primer commit.

## Fase 1 — Servidor y clientes

- [x] Adaptador llama.cpp reproducible y fijado a `sm_120`.
- [x] Publicación exclusiva en `127.0.0.1:18080`.
- [x] Health gate y logs.
- [x] Generadores seguros de configuración Pi/OpenCode.
- [x] Smoke real con Gemma 4 12B.
- [ ] Tool call real desde Pi.
- [x] Chat real desde OpenCode usando configuración temporal.
- [~] Tool call real desde OpenCode; la API y el fixture directo están validados.

## Fase 2 — Perfiles exclusivos

- [x] `start`, `stop`, `switch`, estado y lock.
- [x] Perfiles Qwen y Gemma.
- [x] Validar Qwen → Gemma → Qwen con GPU.
- [x] Confirmar liberación efectiva de VRAM.

## Fase 3 — MTP

- [x] Argumentos declarativos para Gemma 4 MTP.
- [x] Runtime fijado para Qwen MTP/NextN.
- [x] Verificar revisiones y artefactos vigentes mediante APIs upstream.
- [~] Baseline MTP validado; falta barrido comparativo de `spec-draft-n-max`.

## Fase 4 — Benchmarks

- [x] Harness y fixtures iniciales.
- [x] Suite reproducible de performance inicial para ambos perfiles.
- [~] Fixture agentic de tool calling validado; falta Pi end-to-end.
- [ ] Comparar llama.cpp, Ollama y LiteRT-LM con condiciones equivalentes.

## Fase 5 — Catálogo

- [x] Perfil experimental Gemma 4 26B-A4B.
- [ ] Adaptador LiteRT-LM.
- [ ] Canales stable/candidate/experimental.
- [~] Reporte explícito de almacenamiento; limpieza diferida por seguridad.

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
- [ ] Tras finalizar `tui-v2`, incorporar y validar como perfil experimental Gemma 4 v2 Q6_K (`yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2-GGUF`, revisión `190a31365a6b80a692349be34ccdac730cad4fe4`, archivo `gemma4-v2-Q6_K.gguf`); partir de 16k de contexto, GPU completa, Flash Attention y Jinja, y registrar smoke, VRAM y tool calling.
- [ ] Adaptador LiteRT-LM.
- [ ] Canales stable/candidate/experimental.
- [~] Reporte explícito de almacenamiento; limpieza diferida por seguridad.

## Fase 6 — TUI v2

- [x] Reimplementar primitivas en Rust (settings, env, profiles, state, gpu,
      port, http, compose).
- [x] Comandos start, stop, switch, status, profiles, health, logs, doctor
      con paridad 1:1 con `bin/llm-lab`.
- [x] Dashboard de 2 paneles (estado + lista de perfiles) con refresco.
- [x] Overlay con spinner animado y log streamed de `docker compose`.
- [x] Diálogo de confirmación para start, switch y stop.
- [x] Footer con atajos contextuales y pantalla de ayuda.
- [x] Tests de integración + snapshot del dashboard con `TestBackend`.

# Backlog vivo

## Convenciones

- `[x]` implementado y validado.
- `[~]` implementado, pendiente de validación pesada o con GPU.
- `[ ]` pendiente.

## Punto de partida para nuevas sesiones

Estado confirmado al 2026-08-30:

- La rama `feature/cuda13-llama-cpp-upgrade` está publicada y todavía no tiene
  PR; usa `git log origin/main..HEAD` para obtener el estado exacto de commits.
- CUDA 13.0.3 y llama.cpp b10689 están validados en la RTX 5060 Ti con Gemma
  12B, Qwen 3.6 y Qwen 3.8. Gemma 26B es el único perfil cuyo GGUF no está
  descargado.
- Los modelos activos viven en `LLM_LAB_DATA_DIR`; el archivo frío configurable
  usa `LLM_LAB_ARCHIVE_DIR` y no restaura modelos automáticamente.
- La validación rápida canónica es:

  ```bash
  PYTHONPATH=src python3 -m unittest discover -s tests -v
  cargo test --manifest-path tui-v2/Cargo.toml
  ./bin/llm-lab profiles
  ./bin/llm-lab config show --effective
  ./bin/llm-lab doctor
  docker compose config --quiet
  ```

Cada iniciativa siguiente está pensada para una sesión independiente. La sesión
debe leer esta sección, la iniciativa elegida y únicamente los documentos que
allí se indican; no necesita reauditar todo el repositorio salvo que encuentre
evidencia contradictoria.

## Próximas iniciativas priorizadas

### I-01 — PR del upgrade CUDA 13

- [ ] Abrir un PR de `feature/cuda13-llama-cpp-upgrade` hacia `main`.
- Alcance ya cerrado: runtime CUDA/llama.cpp, revalidación de tres modelos,
  suites locales ampliadas, archivo frío, portabilidad CUDA, licencia y créditos.
- Antes del PR: repetir la validación rápida, revisar `git diff
  origin/main...HEAD` y resumir los resultados GPU de `docs/VALIDATION.md`.
- Aceptación: PR con trazabilidad de los commits, controles locales verdes
  y sin archivos locales, modelos, caches ni resultados de benchmark versionados.
- El merge continúa siendo manual.

### I-02 — Benchmarks estándar reproducibles

- [ ] Integrar `llama-bench` de la misma revisión del runtime y guardar JSON con
  `pp512`, `pp2048`, `pp8192`, `tg128` y `tg512`, frío/caliente y MTP on/off.
- [ ] Integrar entornos versionados y opt-in para lm-evaluation-harness, BFCL y
  HumanEval+/MBPP+; ningún comando rápido debe descargar datasets.
- [ ] Definir manifests con versión, seed, muestra, prompt, límites y licencia.
- Empezar por `docs/benchmarking.md`, `benchmarks/run.py` y el Dockerfile.
- Aceptación: un comando documentado por runner, resultados ignorados por Git,
  reanudación segura y comparación de los tres modelos descargados.

### I-03 — Matriz exigente de modelos actuales

- [ ] Ejecutar `quality`, `tools`, `context` y `soak` sobre Qwen 3.6 y Qwen 3.8;
  Gemma 12B ya tiene el primer baseline de estas suites.
- [ ] Añadir contextos 16K y 32K, seguimiento de VRAM por intervalo y detección
  de degradación durante soak.
- [ ] Barrer `spec-draft-n-max` con MTP activado/desactivado y elegir valores por
  perfil usando calidad, latencia y aceptación, no solo tokens/s.
- Empezar por `docs/VALIDATION.md`, `docs/benchmarking.md` y los JSON ignorados
  bajo `benchmark-results/`.
- Aceptación: tabla comparable de los tres perfiles, servidor detenido al final
  y backlog actualizado con evidencia, no impresiones subjetivas.

### I-04 — Primer perfil nuevo orientado a coding

- [ ] Evaluar Qwen3-Coder 30B-A3B Instruct como primera incorporación.
- [ ] Seleccionar GGUF Q3/IQ3, fijar repositorio, revisión, archivo, checksum y
  licencia; comenzar con 16K y luego 32K si queda margen de VRAM.
- [ ] Archivar en HDD si no supera a los perfiles actuales en su rol.
- Empezar por `docs/profile-candidates.md` y `docs/adding-models.md`.
- Aceptación: perfil `experimental`, build en llama.cpp fijado, matriz completa,
  tool calling real y decisión documentada de conservar o descartar.

### I-05 — Perfiles balanced y fast

- [ ] Después de I-04, evaluar Ministral 3 14B Instruct como `general-balanced`.
- [ ] Evaluar Ministral 3 8B Instruct como baseline `fast`.
- [ ] Considerar Phi-4 o Nemotron solo si cubren una necesidad que los perfiles
  anteriores no resuelven.
- Aceptación por modelo: mismos gates de I-04; no agregar perfiles redundantes ni
  descargar varios candidatos en una sola sesión.

### I-06 — Auditoría documental y limpieza

- [ ] Revisar README, `docs/`, decisiones, backlog, ejemplos y ayuda CLI contra
  el comportamiento real; eliminar duplicación, instrucciones obsoletas y TODO
  sin valor verificable.
- [ ] Inventariar scripts, perfiles, clientes y dependencias; proponer antes de
  eliminar cualquier frente que pueda contener trabajo útil.
- [ ] Verificar enlaces, comandos copiables, licencias de terceros, archivos
  ignorados y ausencia de artefactos locales o secretos.
- [ ] Consolidar una ruta pública mínima: instalación, compatibilidad GPU,
  operación, modelos, benchmarks, contribución y troubleshooting.
- Aceptación: documentación coherente desde un clon limpio, backlog reducido a
  trabajo accionable y commit de limpieza separado de cambios funcionales.

### I-07 — CLI y TUI unificadas (diferida)

- [ ] Eliminar la TUI v1 de Python y sus referencias tras confirmar paridad.
- [ ] Mejorar la CLI como única capa de dominio reutilizable: salida JSON
  consistente, errores estables y comandos de benchmarks/archivo frío completos.
- [ ] Convertir `tui-v2` en `tui` predeterminada y cubrir todas las mejoras de la
  CLI, incluidos archivo/restauración, suites nuevas y arquitectura CUDA.
- [ ] Añadir migración documental y comprobar que no queden dos implementaciones
  de lógica operativa.
- Prioridad: diferida hasta completar I-02 a I-05.
- Aceptación: una sola TUI Rust, sin `tui/main.py`, paridad cubierta por tests y
  sin pérdida de comandos ni accesibilidad desde teclado.

## Fase 0 — Bootstrap

- [x] Crear repositorio y documentar el alcance inicial.
- [x] Añadir README, AGENTS.md, licencia y `.gitignore`.
- [x] Definir esquema y registro inicial de perfiles.
- [x] Implementar CLI y pruebas sin GPU.
- [x] Crear primer commit.

## Fase 1 — Servidor y clientes

- [x] Adaptador llama.cpp reproducible y fijado a `sm_120`.
- [x] Runtime actualizado a CUDA 13.0.3 y llama.cpp b10689; los tres modelos
      descargados —Gemma 12B, Qwen 3.6 y Qwen 3.8 27B— pasaron build, health,
      smoke, tool calling, MTP, performance y agent sobre GPU. Se conserva el
      baseline adicional de Qwen 3.8 sobre CUDA 12.8.1/llama.cpp 093adb2.
      Gemma 26B sigue sin descargarse y queda fuera de esta ronda de validación
      pesada.
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
- [x] Suite reproducible de performance para los tres modelos descargados.
- [x] Suites locales `quality`, `tools`, `context` y `soak`, con p95 y metadata
      efectiva de la imagen.
- [ ] I-02: integrar ejecuciones versionadas de llama-bench,
      lm-evaluation-harness, BFCL y HumanEval+/MBPP+ sin descargas implícitas.
- [ ] Ejecutar SWE-bench Mini/Verified con un agente fijado y separar el score
      del modelo del score del sistema completo.
- [~] Fixture agentic de tool calling validado; falta Pi end-to-end.
- [ ] Comparar llama.cpp, Ollama y LiteRT-LM con condiciones equivalentes.

## Fase 5 — Catálogo

- [x] Perfil experimental Gemma 4 26B-A4B.
- [ ] Revaluar después de I-04/I-05 si Gemma 4 v2 Q6_K aporta un rol distinto
      antes de crear otro perfil Gemma; no depende de la TUI.
- [ ] Adaptador LiteRT-LM.
- [ ] Canales stable/candidate/experimental.
- [~] Reporte explícito de almacenamiento; limpieza diferida por seguridad.
- [x] Archivo frío configurable por perfil con restauración explícita.
- [~] Catálogo público de candidatos para 16 GB; falta fijar GGUF, revisión y
      checksum antes de crear perfiles experimentales.

## Fase 6 — TUI v2

- [x] Reimplementar primitivas en Rust (settings, env, profiles, state, gpu,
      port, http, compose).
- [x] Comandos start, stop, switch, status, profiles, health, logs, doctor
      con paridad 1:1 con `bin/llm-lab`.
- [x] Dashboard de 2 paneles con telemetría persistente y contenido contextual.
- [x] Panel derecho para perfiles, spinner y log streamed de `docker compose`.
- [x] Diálogo de confirmación para start, switch y stop.
- [x] Footer con atajos contextuales y pantalla de ayuda.
- [x] Tests de integración + snapshot del dashboard con `TestBackend`.
- [ ] I-07: retirar la TUI v1, promover la TUI Rust como predeterminada y
      recuperar paridad con todas las mejoras posteriores de la CLI.

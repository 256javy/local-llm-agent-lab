# Backlog vivo

## Convenciones

- `[x]` implementado y validado.
- `[~]` implementado, pendiente de validación pesada o con GPU.
- `[ ]` pendiente.
- `P0` siguiente trabajo bloqueante; `P1` alto valor o base necesaria; `P2`
  importante después de P0/P1; `P3` exploratorio o diferido.

La prioridad solo se exige en items `[ ]` o `[~]`. Dentro de la misma prioridad
se respeta el orden y las dependencias documentadas; no implica ejecutar dos
consumidores GPU a la vez.

## Punto de partida para nuevas sesiones

Estado confirmado al 2026-08-31:

- Los PR [#1](https://github.com/256javy/local-llm-agent-lab/pull/1),
  [#2](https://github.com/256javy/local-llm-agent-lab/pull/2),
  [#4](https://github.com/256javy/local-llm-agent-lab/pull/4) y
  [#5](https://github.com/256javy/local-llm-agent-lab/pull/5) están fusionados:
  contienen el upgrade CUDA 13, la promoción de la TUI Rust, `llama-bench`
  nativo y la base inmutable del store de trazas, respectivamente. El PR #3
  documentó el roadmap que conecta benchmarks y trazas.
- CUDA 13.0.3 y llama.cpp b10689 están validados en la RTX 5060 Ti con Gemma
  12B, Qwen 3.6 y Qwen 3.8. Gemma 26B es el único perfil cuyo GGUF no está
  descargado.
- Los modelos activos viven en `LLM_LAB_DATA_DIR`; el archivo frío configurable
  usa `LLM_LAB_ARCHIVE_DIR` y no restaura modelos automáticamente.
- La validación rápida canónica es:

  ```bash
  PYTHONPATH=src python3 -m unittest discover -s tests -v
  cargo test --manifest-path tui/Cargo.toml
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

- [x] Abrir un PR de `feature/cuda13-llama-cpp-upgrade` hacia `main`.
- Alcance ya cerrado: runtime CUDA/llama.cpp, revalidación de tres modelos,
  suites locales ampliadas, archivo frío, portabilidad CUDA, licencia y créditos.
- Antes del PR: repetir la validación rápida, revisar `git diff
  origin/main...HEAD` y resumir los resultados GPU de `docs/VALIDATION.md`.
- Aceptación: PR con trazabilidad de los commits, controles locales verdes
  y sin archivos locales, modelos, caches ni resultados de benchmark versionados.
- El merge continúa siendo manual.

### I-02 — Benchmarks estándar reproducibles

- [x] Documentar las tres capas (inferencia nativa, harness HTTP y trazas reales),
      sus contratos y el plan incremental en
      `docs/plans/trace-and-benchmark-harness.md`.
- [x] **P0** Integrar `llama-bench` de la misma build/revisión del runtime y
      guardar JSON con `pp512`, `pp2048`, `pp8192`, `tg128`, `tg512` y depth
      8K/16K; no descargar modelos, no ejecutar con servidor activo y no
      presentar MTP como medido.
- [ ] **P2** Integrar entornos versionados y opt-in para lm-evaluation-harness,
      BFCL y
  HumanEval+/MBPP+; ningún comando rápido debe descargar datasets.
- [ ] **P2** Definir manifests con versión, seed, muestra, prompt, límites y
      licencia para cada runner externo.
- Empezar por `docs/benchmarking.md`, `benchmarks/run.py` y el Dockerfile.
- Aceptación: un comando documentado por runner, resultados ignorados por Git,
  reanudación segura y comparación de los tres modelos descargados.

### I-03 — Matriz exigente de modelos actuales

- [x] Ejecutar `quality`, `tools`, `context` y `soak` sobre Qwen 3.6 y Qwen 3.8;
  Gemma 12B ya tiene el primer baseline de estas suites.
- [x] Añadir contextos 16K y 32K, seguimiento de VRAM por intervalo y detección
  de degradación durante soak.
- [x] Barrer `spec-draft-n-max` con MTP activado/desactivado y elegir valores por
  perfil usando calidad, latencia y aceptación, no solo tokens/s.
- Empezar por `docs/VALIDATION.md`, `docs/benchmarking.md` y los JSON ignorados
  bajo `benchmark-results/`.
- Aceptación: tabla comparable de los tres perfiles, servidor detenido al final
  y backlog actualizado con evidencia, no impresiones subjetivas.

### I-04 — Primer perfil nuevo orientado a coding

- [ ] **P2** Evaluar Qwen3-Coder 30B-A3B Instruct como primera incorporación.
- [ ] **P2** Seleccionar GGUF Q3/IQ3, fijar repositorio, revisión, archivo, checksum y
  licencia; comenzar con 16K y luego 32K si queda margen de VRAM.
- [ ] **P2** Archivar en HDD si no supera a los perfiles actuales en su rol.
- Empezar por `docs/profile-candidates.md` y `docs/adding-models.md`.
- Aceptación: perfil `experimental`, build en llama.cpp fijado, matriz completa,
  tool calling real y decisión documentada de conservar o descartar.

### I-05 — Perfiles balanced y fast

- [ ] **P3** Después de I-04, evaluar Ministral 3 14B Instruct como `general-balanced`.
- [ ] **P3** Evaluar Ministral 3 8B Instruct como baseline `fast`.
- [ ] **P3** Considerar Phi-4 o Nemotron solo si cubren una necesidad que los perfiles
  anteriores no resuelven.
- Aceptación por modelo: mismos gates de I-04; no agregar perfiles redundantes ni
  descargar varios candidatos en una sola sesión.

### I-06 — Auditoría documental y limpieza

- [ ] **P2** Revisar README, `docs/`, decisiones, backlog, ejemplos y ayuda CLI contra
  el comportamiento real; eliminar duplicación, instrucciones obsoletas y TODO
  sin valor verificable.
- [ ] **P2** Inventariar scripts, perfiles, clientes y dependencias; proponer antes de
  eliminar cualquier frente que pueda contener trabajo útil.
- [ ] **P2** Verificar enlaces, comandos copiables, licencias de terceros, archivos
  ignorados y ausencia de artefactos locales o secretos.
- [ ] **P2** Consolidar una ruta pública mínima: instalación, compatibilidad GPU,
  operación, modelos, benchmarks, contribución y troubleshooting.
- Aceptación: documentación coherente desde un clon limpio, backlog reducido a
  trabajo accionable y commit de limpieza separado de cambios funcionales.

### I-07 — CLI y TUI unificadas (en curso)

- [x] Eliminar la TUI v1 de Python y sus referencias tras confirmar que estaba
      aislada y que la TUI Rust cubría sus comandos operativos.
- [ ] **P1** Mejorar la CLI como única capa de dominio reutilizable: salida JSON
  consistente, errores estables y comandos de benchmarks/archivo frío completos.
- [ ] **P3** Cubrir en la TUI las mejoras posteriores de la CLI, incluidos
      archivo/restauración, suites nuevas y arquitectura CUDA.
- [x] Promover la TUI Rust de `tui-v2/` a `tui/`, actualizar la ruta documental
      y comprobar que no queden dos implementaciones de lógica operativa.
- Prioridad: la consolidación de la TUI está completa; las mejoras funcionales
  restantes siguen diferidas hasta completar I-02 a I-05.
- Aceptación: una sola TUI Rust, sin `tui/main.py`, paridad cubierta por tests y
  sin pérdida de comandos ni accesibilidad desde teclado.

### I-08 — Importación y normalización de trazas

- [x] Implementar store local versionado e inmutable bajo `.local/`,
      manifests, hashes, escrituras atómicas y eventos JSONL con procedencia.
- [x] Implementar adaptador Pi para JSONL 0.84.x con mensajes, tools,
      cambios de modelo/thinking, compactions, ramas y tipos desconocidos.
- [x] Implementar adaptador OpenCode usando `session list`/`export`, con
      detección de versión/capacidades y preservación del export original.
- [x] Exponer `trace capture`, `list` y `show`, con `--help`, errores
      accionables y fixtures totalmente sintéticos.
- Empezar por `docs/trace-analysis.md` y el slice S2 del plan.
- Aceptación cumplida: ambos fixtures producen manifests/eventos validados,
  ordenados y trazables al raw sin acceder a sesiones reales durante tests.

### I-09 — Captura exacta, contexto y privacidad

- [ ] **P1** Implementar `trace begin`/`finish` y snapshots Git read-only para
      clean/dirty, staged/unstaged, untracked, detached HEAD y no-Git.
- [ ] **P1** Registrar contexto `discovered`, `confirmed_loaded` o `unknown`,
      perfil/runtime y configuración relevante sin afirmar carga no observable.
- [ ] **P1** Aplicar permisos restrictivos, límites, exclusiones, detección de
      secretos y reporte de redacción antes de exportar; contenido untracked
      queda opt-in.
- Aceptación: la captura no muta el checkout, declara información no recuperable
  y un bundle sintético no filtra los secretos de prueba.

### I-10 — Outcome, anotaciones y métricas

- [ ] **P1** Implementar outcome `pass|partial|fail|unknown` separado de
      completion declarada, aceptación humana y corrección requerida.
- [ ] **P1** Anotar intervenciones por tipo y event ID sin modificar raw ni
      normalizado.
- [ ] **P1** Calcular métricas deterministas e idempotentes con namespaces de
      procedencia; no penalizar automáticamente la autocorrección.
- Aceptación: `trace annotate/show` distingue requisito nuevo, corrección y
  verificación; los conteos se reproducen desde el mismo trace.

### I-11 — Review frontier estructurado

- [ ] **P2** Generar un review bundle local y redactado con prompt/rúbrica
      versionados; no realizar envíos de red automáticos.
- [ ] **P2** Validar review JSON con evidencia/eventos, severidad, root cause,
      confianza, capa responsable y recomendación, y renderizar Markdown.
- Aceptación: un reviewer manual puede producir un resultado validable sin
  acceso a la sesión original ni dependencia de API propietaria.

### I-12 — Cases, evals y agregación

- [ ] **P2** Implementar promociones explícitas trace -> case -> eval con
      referencias inmutables y reporte de evidencia faltante.
- [ ] **P2** Agregar estadísticas sobre outcomes, intervenciones y causas de
      reviews, distinguiendo observado de inferido y sin score global.
- Aceptación: un fixture puede promoverse, o fallar con requisitos concretos,
  y `cases stats` es reproducible sobre JSON versionado.

### I-13 — Replay contrafactual

- [ ] **P3** Definir manifest de variantes para mismo snapshot/tarea/harness con
      cambios de modelo, configuración o reglas.
- [ ] **P3** Decidir y documentar aislamiento, permisos, costes y verificación
      antes de ejecutar agentes automáticamente.
- [ ] **P3** Implementar preflight/replay/comparación solo después de que I-12
      produzca evals reproducibles.
- Aceptación inicial: matriz validable y rechazo seguro de evals incompletos;
  automatización de agentes no es requisito del primer slice.

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
- [ ] **P1** Tool call real desde Pi.
- [x] Chat real desde OpenCode usando configuración temporal.
- [~] **P1** Tool call real desde OpenCode; la API y el fixture directo están validados.

## Fase 2 — Perfiles exclusivos

- [x] `start`, `stop`, `switch`, estado y lock.
- [x] Perfiles Qwen y Gemma.
- [x] Validar Qwen → Gemma → Qwen con GPU.
- [x] Confirmar liberación efectiva de VRAM.

## Fase 3 — MTP

- [x] Argumentos declarativos para Gemma 4 MTP.
- [x] Runtime fijado para Qwen MTP/NextN.
- [x] Verificar revisiones y artefactos vigentes mediante APIs upstream.
- [x] Baseline MTP y barrido comparativo de `spec-draft-n-max` validados.

## Fase 4 — Benchmarks

- [x] Harness y fixtures iniciales.
- [x] Suite reproducible de performance para los tres modelos descargados.
- [x] Suites locales `quality`, `tools`, `context` y `soak`, con p95 y metadata
      efectiva de la imagen.
- [x] **P0** I-02: integrar `llama-bench` nativo de la misma build del runtime.
- [ ] **P2** I-02: integrar ejecuciones versionadas de
      lm-evaluation-harness, BFCL y HumanEval+/MBPP+ sin descargas implícitas.
- [ ] **P3** Ejecutar SWE-bench Mini/Verified con un agente fijado y separar el score
      del modelo del score del sistema completo.
- [~] **P1** Fixture agentic de tool calling validado; falta Pi end-to-end.
- [ ] **P3** Comparar llama.cpp, Ollama y LiteRT-LM con condiciones equivalentes.

## Fase 5 — Catálogo

- [x] Perfil experimental Gemma 4 26B-A4B.
- [ ] **P3** Revaluar después de I-04/I-05 si Gemma 4 v2 Q6_K aporta un rol distinto
      antes de crear otro perfil Gemma; no depende de la TUI.
- [ ] **P3** Adaptador LiteRT-LM.
- [ ] **P2** Canales stable/candidate/experimental.
- [~] **P2** Reporte explícito de almacenamiento; limpieza diferida por seguridad.
- [x] Archivo frío configurable por perfil con restauración explícita.
- [~] **P2** Catálogo público de candidatos para 16 GB; falta fijar GGUF, revisión y
      checksum antes de crear perfiles experimentales.

## Fase 6 — TUI

- [x] Reimplementar primitivas en Rust (settings, env, profiles, state, gpu,
      port, http, compose).
- [x] Comandos start, stop, switch, status, profiles, health, logs, doctor
      con paridad 1:1 con `bin/llm-lab`.
- [x] Dashboard de 2 paneles con telemetría persistente y contenido contextual.
- [x] Panel derecho para perfiles, spinner y log streamed de `docker compose`.
- [x] Diálogo de confirmación para start, switch y stop.
- [x] Footer con atajos contextuales y pantalla de ayuda.
- [x] Tests de integración + snapshot del dashboard con `TestBackend`.
- [x] I-07: retirar la TUI v1 y promover la TUI Rust como predeterminada.
- [ ] **P3** I-07: recuperar paridad con todas las mejoras posteriores de la CLI.

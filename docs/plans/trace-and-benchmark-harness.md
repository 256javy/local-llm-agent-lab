# Plan técnico: benchmark nativo y trazas de agentes

## Objetivo y límites

El proyecto debe responder con evidencia a tres preguntas distintas:

| Capa | Comando | Mide | No demuestra |
| --- | --- | --- | --- |
| Inferencia nativa | `llm-lab bench <perfil>` | throughput de `llama-bench` | calidad agentic o MTP del servidor |
| Harness controlado | `llm-lab benchmark <perfil> --suite ...` | API, fixtures, tools y estabilidad | resultado de una tarea real |
| Trabajo real | `llm-lab trace ...` | trayectoria, contexto, correcciones y verificación | causalidad sin replay controlado |

Se mantiene filesystem + JSON/JSONL, Python estándar, perfiles declarativos y
un solo consumidor GPU. No se introduce base de datos, servicio, dashboard,
API propietaria de reviewer ni cambio de schema de perfiles en el primer ciclo.

## Arquitectura propuesta

```text
src/llm_lab/
  native_bench.py          # matriz, traducción y ejecución llama-bench
  traces/
    models.py              # schemas/versiones y validación
    store.py               # layout, IDs, hashes y escrituras atómicas
    normalize.py           # despacho de adaptadores
    adapters/{pi,opencode}.py
    repository.py          # snapshots Git read-only
    context.py             # discovered vs confirmed_loaded
    redact.py              # detección y export seguro
    annotations.py
    metrics.py
    reviews.py             # bundle y validación de review
    promotion.py           # trace -> case -> eval
benchmarks/native-matrix.json
tests/fixtures/traces/      # solo datos sintéticos
```

Archivos existentes a modificar por slice: Dockerfile y Compose para
`llama-bench`; `cli.py` para subcomandos; `core.py` solo para utilidades
reutilizables; `.gitignore`; `docs/benchmarking.md`, `docs/trace-analysis.md`,
operación y backlog. La TUI no bloquea el MVP: consumirá estos comandos cuando
la CLI tenga salida JSON y errores estables.

## Contratos CLI

```text
llm-lab bench <perfil> [--matrix standard] [--output <ruta>]
llm-lab benchmark <perfil> --suite <suite>
llm-lab trace list|show <id>
llm-lab trace capture pi|opencode --session <id>
llm-lab trace begin --client pi|opencode [--repo <ruta>]
llm-lab trace finish <id>
llm-lab trace annotate <id> [--event <id>]
llm-lab trace review-bundle <id> [--output <ruta>]
llm-lab trace promote <id> --case
llm-lab case promote <id> --eval
llm-lab cases stats
```

Cada nivel tendrá `--help`. Los comandos no interactivos aceptarán JSON y
errores con remedio concreto. `trace begin` imprimirá el ID necesario para
`finish`; el estado activo se guardará fuera del repositorio y se negará a
sobrescribir otra captura abierta.

## Schemas v1

- `trace-manifest`: identidad, timestamps, source/version, hashes, perfil,
  runtime, repositorio, capacidades capturadas y warnings.
- `normalized-event`: identidad/orden/tipo/sourceRef/provenance/payload.
- `repository-snapshot`: Git/ref/status/patches/untracked y completitud.
- `effective-context`: elementos descubiertos, cargados, desconocidos y fuente
  de evidencia.
- `annotations`: outcome e intervenciones humanas sin alterar eventos.
- `metrics`: namespaces `observed`, `calculated` y `reviewer_inferred`.
- `review`: reviewer/rúbrica/issues/evidence/rootCause/confidence/recommendation.
- `case` y `eval`: referencias inmutables a artefactos y requisitos de replay.

Primero se implementará validación manual con tipos/datos Python; JSON Schema
versionado puede agregarse si aporta interoperabilidad sin duplicar reglas.

## Slices y criterios de cierre

### S0. Contratos documentales

Este documento, `trace-analysis.md`, benchmarking y backlog coherentes; enlaces
válidos; ningún dato real versionado. Es el entregable de diseño.

### S1. `llama-bench` usable

- Compilar y copiar `llama-server` y `llama-bench` desde la misma revisión,
  toolchain, CUDA y backend.
- Reutilizar `/models/<perfil>/<archivo>`; nunca descargar. Si falta, indicar
  `llm-lab pull <perfil>`.
- Tomar el lock y rechazar cualquier estado/contenedor administrado activo; no
  detener procesos ajenos.
- Traducir solo `ngl`, `fa`, `ctk`, `ctv`, `sm`, `mg` y mmap cuando la revisión
  lo soporte. Reportar argumentos ignorados; MTP/server sampling no se traduce.
- Ejecutar matriz central pp512/2048/8192, tg128/512 y tg128 con depth
  8192/16384, cinco repeticiones, recortando depth contra `contextSize`.
- Consumir `llama-bench -o json`, preservar raw y producir manifest/tabla sin
  score compuesto. Separar warmup normal, `--no-warmup` y cold process externo.
- Tests de traducción, límites, lifecycle, modelo ausente y parseo; smoke manual
  en la GPU. No se necesita una segunda imagen.

Riesgo real: el entrypoint actual siempre inicia `llama-server`; Compose
necesita un modo `bench` o `entrypoint` explícito. `llama-bench` soporta salida
JSON, repeticiones, depth, KV types y metadata de build/hardware en upstream.

### S2. Importación post-hoc

Store + schemas + fixtures; adaptador Pi JSONL 0.84.x; adaptador OpenCode por
`export`; preservación raw/hash; lista/show; eventos desconocidos y campos
ausentes tolerados. Cierre: ambos fixtures producen eventos ordenados y un
manifest validado sin acceder a sesiones reales en tests.

### S3. Captura exacta y privacidad

`begin`/`finish`, snapshots Git read-only, contexto efectivo, permisos locales,
redacción/reporte y advertencias de export. Cierre: clean/dirty/staged/untracked,
detached HEAD, repositorio no Git, symlinks y límites de tamaño probados.

### S4. Outcome y métricas

Anotación no destructiva, escalas cerradas y conteos deterministas. Cierre:
provenance visible, reejecución idempotente de métricas y distinción entre
corrección humana, requisito nuevo y autocorrección observable.

### S5. Review bundle

Bundle local, rúbrica/prompt versionados, schema de review, validador y render
Markdown. Cierre: un reviewer manual puede devolver JSON validable; no se
envía nada por red automáticamente.

### S6. Cases y evals

Promoción explícita, referencias inmutables, requisitos de reproducibilidad y
stats sobre reviews. Cierre: un case sintético se promueve a eval o explica qué
evidencia falta. Replay queda fuera.

### S7. Fundación de replay contrafactual

Especificar matriz `same snapshot/task/harness` con variantes de
modelo/config/reglas; preflight y comparación sin score global. La ejecución
aislada requiere una decisión posterior sobre worktrees/contenedores y política
de permisos antes de automatizar agentes.

## Matriz transversal de pruebas

Cada slice incorpora sus tests; el orden de riesgo es: normalización Pi,
normalización OpenCode, schemas de manifest/review, captura Git clean/dirty,
staged/unstaged/untracked, traducción perfil -> `llama-bench`, recorte de depth,
sanitización, agregación y compatibilidad de la CLI existente. Se usarán
fixtures sintéticos y repositorios temporales; nunca una sesión real completa.

Al cerrar cada slice: tests Python, test/clippy de TUI si se toca, comandos
manuales razonables, `profiles`, configuración efectiva, `doctor`, Compose,
documentación, limitaciones reales y siguiente slice. Las pruebas que descargan
datasets/modelos o construyen runtimes siguen siendo opt-in y se registran en
este backlog.

## Dependencias y riesgos

- Pi y OpenCode evolucionan: fijar fixtures por versión, detección de capacidad
  y fallos explícitos. Verificar de nuevo antes de implementar adaptadores.
- Una exportación no prueba el system prompt efectivo; usar `unknown`.
- Patches y untracked pueden contener secretos o ser enormes; límites, opt-in y
  redacción son parte del primer slice exacto, no limpieza posterior.
- Hashes aseguran integridad, no confidencialidad. No guardar secretos en
  manifests ni logs.
- Captura post-hoc es necesariamente parcial. Replay exacto solo puede prometerse
  si el eval satisface todos los requisitos registrados.
- MTP no es medido por `llama-bench`; su efecto corresponde al benchmark HTTP.
- Context depth debe respetar el perfil y el coste de KV/VRAM, no solo aceptar
  una bandera sintácticamente.

## Ajustes respecto a la propuesta inicial

1. Separar `llama-bench` de lm-evaluation-harness/BFCL/HumanEval: son entregas y
   dependencias distintas.
2. No llamar “cold” a `--no-warmup`; cold process/model load será otra medición.
3. No capturar tar de untracked por defecto; comenzar con inventario/hash y
   contenido opt-in con límites.
4. No asumir que AGENTS/config encontrados fueron cargados ni que OpenCode
   siempre ofrece `--sanitize`.
5. No integrar reviewers propietarios antes de validar bundle/schema manual.
6. Agregación básica sigue a reviews/cases; replay contrafactual queda último
   porque exige aislamiento y una política de ejecución segura.

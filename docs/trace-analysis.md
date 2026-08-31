# Análisis de trazas reales

Este frente estudia tareas reales ejecutadas por Pi u OpenCode. No reemplaza
`llama-bench` ni las suites HTTP: registra qué vio e hizo un agente, qué tuvo
que corregir una persona y qué evidencia permite explicar el resultado.

## Conceptos y procedencia

- **Trace**: copia inmutable de una sesión original, su normalización y el estado
  reproducible que pudo capturarse. Puede estar incompleta y debe declararlo.
- **Case**: trace que una persona promueve explícitamente para conservar,
  anotar o revisar.
- **Eval case**: case con estado inicial, tarea, contexto y verificación
  suficientes para repetir una comparación controlada.
- **Review**: inferencias de un revisor sobre una versión concreta del case; no
  modifica la fuente ni convierte una hipótesis en hecho.

Todo campo analítico indicará procedencia: `observed`, `calculated`,
`human_annotated` o `reviewer_inferred`. El reasoning solo se registrará como
`observed_reasoning` cuando el cliente realmente lo exporte; el sistema nunca
dependerá de disponer de chain-of-thought.

```text
trabajo real -> trace -> revisión -> case -> eval case -> repetición
                   \-> archivo       ^         ^
                        persona decide cada promoción
```

## Fuentes soportables

La versión instalada de Pi es 0.84.4. Pi conserva JSONL bajo su directorio de
sesiones, con header y entradas enlazadas por `id`/`parentId`. Su formato
documentado representa mensajes, resultados de herramientas, cambios de
modelo/thinking, compactions y resúmenes de ramas. El adaptador debe leer JSONL,
preservar IDs y tipos desconocidos y fijar en fixtures la versión del formato
que soporta; no debe parsear la pantalla del terminal.

La versión instalada de OpenCode es 1.18.25. Su CLI documenta
`opencode session list --format json` y `opencode export <sessionID>` como
fuente JSON oficial; `--sanitize` existe en la documentación actual, pero debe
detectarse por versión/capacidad y no asumirse. La importación conservará tanto
el export original como la representación normalizada. La sanitización oficial
es una capa adicional, no evidencia de que el bundle sea seguro.

Estas interfaces externas pueden cambiar. Cada trace guardará nombre, versión,
comando de captura y hash del raw; un adaptador incompatible debe fallar con un
mensaje accionable, nunca descartar eventos silenciosamente.

Evidencia upstream verificada de nuevo el 2026-08-31:

- [formato de sesiones Pi](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/session-format.md),
  [SDK/eventos Pi](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/sdk.md)
  y [compaction/branch summaries](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/compaction.md);
- [CLI oficial de OpenCode](https://opencode.ai/docs/cli/), incluyendo
  `session list`, `export` y la opción de sanitización documentada.

## Almacenamiento local

El valor predeterminado será `.local/`, ya ignorado por Git:

```text
.local/
  traces/<trace-id>/
    manifest.json
    raw/<archivo original o export>
    normalized/events.jsonl
    repository/{initial,final}/
    effective-context/
    annotations.json
    metrics.json
    reviews/<review-id>/{review.json,review.md}
  cases/<case-id>/manifest.json
  evals/<eval-id>/manifest.json
  review-bundles/<bundle-id>/
```

Los manifests, eventos, anotaciones, métricas y reviews tendrán
`schemaVersion`. Las escrituras usarán archivo temporal y rename atómico. Raw
y snapshots serán inmutables; una recaptura crea una nueva revisión. Solo se
versionarán fixtures sintéticos mínimos.

El store v1 ya implementado publica cada trace completo mediante rename desde
un directorio temporal, rechaza IDs existentes, calcula SHA-256 para raw y
eventos normalizados y aplica permisos `0700` a directorios, `0600` a metadata
y eventos, y `0400` a la copia raw. Los adaptadores de clientes serán quienes
construyan estos artefactos; esta capa no accede por sí sola a sesiones reales.

## Importación post-hoc disponible

La CLI importa sesiones terminadas sin modificar la fuente:

```bash
./bin/llm-lab trace capture pi --session <id-o-ruta-jsonl>
./bin/llm-lab trace capture opencode --session <id>
./bin/llm-lab trace list [--json]
./bin/llm-lab trace show <trace-id> [--manifest-only] [--json]
```

Para Pi, `--session` acepta el ID del header, el nombre del archivo bajo
`~/.pi/agent/sessions` o una ruta exacta. El adaptador tolera versiones del
formato desde v1 y registra la versión encontrada; normaliza mensajes, tool
calls/resultados, reasoning exportado, cambios de modelo/thinking, compactions
y ramas. Un tipo desconocido no se descarta: queda como `system_event`, con
referencia a la línea raw y una advertencia en el manifest.

Para OpenCode, la captura detecta la versión instalada, comprueba el ID mediante
`session list --format json` y conserva la salida original de `export`. Luego
normaliza mensajes y partes conocidas. No usa `--sanitize`: el raw inmutable es
la evidencia fuente y la redacción exportable todavía no está implementada.

`trace list` lee manifests y `trace show` valida y presenta los eventos. Ambos
admiten `--json`; `--store` permite inspeccionar otro store explícito. Los tests
usan fixtures totalmente sintéticos de Pi 0.84/formato v3 y OpenCode 1.18, sin
acceder a sesiones reales.

## Eventos normalizados

Cada línea de `events.jsonl` incluirá al menos `schemaVersion`, `eventId`,
`sequence`, `type`, `timestamp` si existe, `sourceRef`, `provenance` y
`payload`. Tipos iniciales:

```text
user_message          assistant_message       observed_reasoning
tool_call             tool_result             error
model_change          thinking_level_change   compaction
branch                human_intervention      system_event
```

Los campos opcionales pueden faltar. Un evento fuente desconocido se conserva
como `system_event` con referencia al raw y advertencia de compatibilidad.

## Estado del repositorio

La captura exacta (`trace begin`/`trace finish`) registrará, sin modificar el
checkout: raíz, `HEAD`, branch o detached HEAD, remotes sin credenciales,
submódulos, `git status --porcelain=v2`, patch staged, patch unstaged y una
lista de archivos no rastreados. Si el usuario opta por preservar sus contenidos,
se empaquetarán fuera de Git con paths relativos seguros, límites configurables,
hashes y exclusión predeterminada de `.git`, `.env`, credenciales, caches,
modelos y el propio almacén `.local`.

La captura post-hoc no puede reconstruir con certeza el estado inicial. El
manifest debe marcar cada componente como `captured`, `inferred` o
`unavailable`. No se ejecutará `reset`, `checkout`, `stash` ni otra mutación.
`tar.zst` queda como extensión opcional: la primera versión puede usar tar sin
compresión para no sumar una dependencia que Python estándar no garantiza.

## Contexto efectivo

Se separará `discovered` de `confirmed_loaded`. La existencia de `AGENTS.md`,
configuración o skills no demuestra que el harness los aplicó. Se capturarán,
cuando la fuente lo permita, modelo/perfil, contexto, argumentos del runtime,
system/developer prompt observado, reglas raíz y anidadas, configuración Pi u
OpenCode relevante y definiciones/metadatos de herramientas. Lo no observable
quedará como `unknown`, no como `false`.

## Privacidad y redacción

Traces y bundles pueden contener código propietario, rutas, prompts, URLs y
secretos. La captura raw local preserva evidencia y por eso debe tener permisos
restrictivos. Antes de exportar se aplicará redacción básica para claves/tokens,
passwords, PEM privadas, `.env` y archivos de credenciales, produciendo un
reporte de coincidencias y omisiones. No se imprimirá el valor detectado.

Un bundle para un revisor externo mostrará una advertencia y requerirá una
acción explícita. La redacción heurística no es DLP y nunca podrá etiquetar un
bundle como “seguro”.

## Outcome, anotaciones y métricas

El outcome usa `pass`, `partial`, `fail` o `unknown` y separa
`agentDeclaredComplete`, `humanAccepted` y `requiredHumanCorrection`. Las
intervenciones humanas se anotan aparte como `clarification`, `new_requirement`,
`human_correction`, `missed_requirement`, `bug_report`,
`verification_request` u `other`, siempre enlazadas a eventos cuando sea
posible.

Métricas deterministas (`observed.*`) incluyen turnos, tools, errores,
reintentos observables, compactions, archivos, tests, duración y tokens si la
fuente los da. `self_corrected_errors`, `premature_completion` o tool calls
innecesarias requieren reglas explícitas o revisión y se guardan bajo
`calculated.*` o `reviewer_inferred.*`, nunca mezcladas con conteos observados.

## Review, cases y evals

`trace review-bundle` generará un bundle autocontenido con manifest, sesión
normalizada, outcome, anotaciones, estado Git, contexto efectivo y prompt de
rúbrica versionado. El resultado esperado es JSON validable y Markdown. Cada
issue referencia eventos, severidad, causa probable, confianza, capa
responsable y cambio concreto. La taxonomía inicial cubre capacidad del modelo,
ambigüedad, prompts/reglas, selección/compaction de contexto, herramientas,
verificación, completion, harness, runtime, requisito humano faltante y
`unknown`.

La rúbrica cubrirá comprensión de tarea, descubrimiento/selección de contexto,
seguimiento de instrucciones, navegación del repo, selección y eficiencia de
tools, interpretación de resultados, recuperación y autocorrección, estrategia
de verificación, criterio de completion, intervención humana, compaction/pérdida
de contexto, influencia del harness y límites de capacidad del modelo. El
reviewer debe proponer el cambio más pequeño en la capa responsable; no asumir
que todo se resuelve cambiando el system prompt.

Promover trace -> case -> eval es siempre explícito. Un eval debe identificar
estado inicial, tarea, reglas/contexto, harness, perfil y verificación esperada.
Replay automático, contrafactuales y agregación se construirán después sobre
estos contratos; no se define un score global.

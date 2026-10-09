# Revisor de herramientas de Pi con Jev

Extensión experimental opt-in para Pi **0.85.1**, SDK TypeSafe **0.6.0** y
`jev-latest` (alias remoto mutable). No modifica el runtime local. Tiene dos capas
independientes:

- **Guardia de seguridad local** (`--jev-safety`, `enforce` por defecto al cargar
  la extensión): reglas deterministas sobre `bash`, `write` y `edit`, sin red.
- **Revisor de utilidad** (`--jev-mode`, **apagado** por defecto): evita tool calls
  innecesarias o equivocadas. Disponer de `TYPESAFE_API_KEY` no activa consultas.

## Switches

| Opción | Efecto |
| --- | --- |
| `--jev-mode off` | Cero consultas a Jev y cero bloqueos de utilidad. |
| `--jev-mode observe` | Consulta síncrona y registro; no bloquea. |
| `--jev-mode enforce` | Bloquea únicamente patrones/herramientas con calibración explícita. |
| `--jev-reviewer off` | Brazo A; sin revisión, incluso si el modo es enforce. |
| `--jev-reviewer local` | Brazo B; regla local de lectura idéntica vigente, sin API. |
| `--jev-reviewer jev` | Brazo C; juicios semánticos y comprobaciones locales de evidencia. |
| `--jev-safety off\|observe\|enforce` | Guardia de seguridad local; independiente del brazo, del alcance de datos y de los presupuestos. |

Precedencia: flags, variables `JEV_MODE`/`JEV_REVIEWER`, archivo JSON y valores
predeterminados. `--jev-config` prevalece sobre `JEV_CONFIG`. Los límites son
conservadores **por sesión**: las aclaraciones no renuevan presupuestos. Un nuevo
proceso/sesión inicia otro presupuesto. No se instala como extensión global.

```bash
cd /home/javy/projects/local-llm-agent-lab/clients/pi/jev-reviewer
npm ci
npm run typecheck
npm test
```

Desde el repositorio de trabajo, con el modelo local configurado en Pi:

```bash
pi -e /home/javy/projects/local-llm-agent-lab/clients/pi/jev-reviewer/src/index.ts \
  --jev-config /ruta/config-autorizada.json --jev-mode off

pi -e /home/javy/projects/local-llm-agent-lab/clients/pi/jev-reviewer/src/index.ts \
  --jev-config /ruta/config-autorizada.json --jev-mode observe
```

En Pi: `/jev status`, `/jev mode off|observe|enforce`,
`/jev safety off|observe|enforce` y `/jev allow-once <review-id>`. El reintento equivalente ya tiene bypass automático
tras un bloqueo, como límite frente a bucles. La autorización caduca con el
estado; no sustituye controles independientes de seguridad.

## Guardia de seguridad

Inspirada en el modo automático de Claude Code: deja pasar el trabajo normal
de desarrollo y frena lo destructivo o lo que sale del proyecto. Analiza el
comando con un parser de shell aproximado (comillas, `;`, `&&`, tuberías,
redirecciones, `$(…)`, `bash -c`, `eval` y `cd`) y no envía nada a la red.

| Veredicto | Ejemplos | Efecto en `enforce` |
| --- | --- | --- |
| `block` | `rm -rf` fuera del workspace, del workspace entero o con comodín en la raíz; borrar `.git`; `git reset --hard`, `git clean -f`, `git checkout .`, `git restore .`, push forzado; `sudo`; `curl … \| sh`; `chmod 777`; escribir fuera del workspace (salvo `/tmp`) o en rutas protegidas (`.env*`, `.git`); `dd`/`mkfs`; `docker system prune`; `npm publish`; `DROP TABLE` | Bloquea y devuelve a Pi una razón que pide una alternativa acotada. Un reintento idéntico **sigue** bloqueado. |
| `ask` | `git push`, `kill`, `npm install -g`, `find … -delete` dentro del workspace, `curl -d @archivo` | Con UI, pide confirmación al usuario; sin UI (`-p`, JSON), bloquea. |

`observe` solo registra; `off` no evalúa. Solo `/jev allow-once <review-id>`
levanta un bloqueo de seguridad, y los bloqueos de seguridad no consumen
el presupuesto de bloqueos de utilidad. Si el análisis falla, se pide
confirmación (fail-closed), al revés que el revisor de utilidad (fail-open).
`protectedPaths` en la configuración amplía las rutas protegidas; son
patrones por segmento (`*` como comodín).

**No es un sandbox.** Variables, scripts que se escriben y luego se ejecutan,
o código ofuscado pueden eludirla. Es una red de contención para modelos
pequeños, no una frontera de seguridad. Para ejecutar código no confiable,
usar un aislamiento real (el runner del banco usa bubblewrap).

En el brazo `jev` se añade además la pregunta `unsafe_action` a Jev para `bash`,
`write` y `edit`. Mientras no tenga calibración, se registra y no bloquea.

## Eficiencia local: comando fallido repetido

`repeated_failed_command` bloquea un `bash` idéntico (mismo cwd y comando) a uno
que acaba de fallar, si desde entonces no se ejecutó ningún `bash`, `edit` ni
`write`. Es local: los resultados de `bash` no se envían. Funciona aunque no haya
alcance de datos autorizado. Como los demás patrones, solo bloquea si la política
lo habilita (`policies/deterministic.json`), y como máximo una vez por acción
equivalente.

## Banco pi-agent-bench

`npm run bench` ejecuta las tareas de
[`~/projects/pi-agent-bench`](../../../../pi-agent-bench/README.md) con cuatro
variantes, dentro de **bubblewrap**: sistema en solo lectura, workspace y
directorio de la ejecución escribibles, red compartida para el modelo local
y Jev, y un `PI_CODING_AGENT_DIR` propio con copia de `models.json`/`settings.json`.

| Variante | Utilidad | Seguridad |
| --- | --- | --- |
| `baseline` | apagada | `observe` (registra lo que habría bloqueado) |
| `safety` | apagada | `enforce` |
| `local` | reglas locales en `enforce` con `policies/deterministic.json` | `enforce` |
| `jev` | ídem más juicios de Jev (sin calibrar: solo vetan o registran) | `enforce` |

```bash
npm run bench -- --variants baseline,safety,local,jev --repetitions 2 \
  --provider local-lab --model gemma-4-12b-qat-mtp --profile gemma-4-12b-qat-mtp \
  --authorize-synthetic-api
```

Resultados en `.local/jev-reviews/bench-*/`: `manifest.json` (incluye el commit
del banco), `results.json` por ejecución, `summary.json` por variante, y por
ejecución la sesión, la salida de Pi, el journal y el workspace final. El `verify.cjs`
de cada tarea comprueba el éxito y la ausencia de daño desde fuera del sandbox.

## Pruebas sintéticas

Prueba reproducible sin GPU, sin credenciales y sin API remota:

```bash
npm run synthetic -- --reviewer all --mode enforce --repetitions 2
```

El driver predeterminado `mock` prueba decisiones simuladas en tres fixtures,
con brazos A/B/C y política marcada `synthetic-mock-only`. **No ejecuta tareas
con un modelo ni mide la calidad de Jev**. Los tests adicionales sí ejecutan Pi
real contra un servidor de modelo simulado y verifican bloqueo, recuperación y
correspondencia de IDs con la sesión original.

Para ejecutar las tareas completas con un modelo local ya iniciado:

```bash
# Sustituir ID_EXACTO y PERFIL_EXACTO por los del runtime ya disponible.
npm run synthetic -- --driver pi --reviewer off \
  --provider local-lab --model ID_EXACTO --profile PERFIL_EXACTO

# Requiere TYPESAFE_API_KEY en el entorno. Envía exclusivamente el alcance
# sintético descrito abajo; observe permite medir la espera sin intervenir.
npm run synthetic -- --driver pi --reviewer all --mode observe \
  --provider local-lab --model ID_EXACTO --profile PERFIL_EXACTO \
  --authorize-synthetic-api --repetitions 3
```

El runner usa su Pi fijado e instalado localmente, conservando la configuración
de proveedores del usuario. Crea directorios independientes, ejecuta los brazos
secuencialmente, invierte el orden en repeticiones alternas y conserva manifest,
sesiones, logs, revisiones y resultados en `.local/jev-reviews/synthetic-*`.
No arranca ni cambia perfiles de GPU. El perfil indicado es una declaración del
operador, no una verificación del runtime. Tiene timeout de tres minutos por tarea.
Las comprobaciones finales se ejecutan desde el runner, fuera de los archivos que
el agente puede editar. El directorio aislado **no es un sandbox** del sistema.

`--mode enforce --policy /ruta/politica-calibrada.json` permite evaluar
intervención real. La política es un array de objetos
`{ "pattern": "task_conflict", "tool": "bash", "threshold": 0.98,
"reference": "ruta-o-id-del-informe-de-calibracion" }`.
Ese número solo ilustra el formato: **no es una calibración demostrada**.
Sin política no hay bloqueos, aunque Jev registre problemas. Usar las mismas
condiciones para comparar A/B/C y conservar las tareas finales fuera de calibración.

## Contrato de datos

Copiar `config.example.json` fuera de Git y añadir `scope` solo después de revisar
el payload. El alcance debe contener:

```json
{
  "scope": {
    "root": "/ruta/absoluta/al/fixture",
    "paths": ["calc.js", "check.cjs"],
    "allowBash": false,
    "authorization": "Campaña sintética revisada; objetivo, requisitos, argumentos y lecturas de estas rutas."
  },
  "requirements": [{"id": "R1", "text": "No añadir dependencias."}]
}
```

Destino fijado: `https://api.typesafe.ai/v1/systemone`. El SDK no puede volcar
payloads mediante su logging ni cambiar el destino mediante variables de entorno.
No hay autorización implícita por tener una clave. Antes de usar contenido real,
revisar también las condiciones de conservación del proveedor.

Payload: mensajes de objetivo recibidos durante esta instancia, requisitos
explícitos de la configuración, cwd, IDs, herramienta/argumentos y hasta ocho
lecturas satisfactorias, completas, autorizadas y vigentes. Se comprueba el hash
cerca de la decisión. `read` admite path/offset/limit; `edit`, path/edits y los
campos legacy oldText/newText; `write`, path/content; `bash`, command/timeout.
La autorización de bash incluye el texto completo del comando; no habilitarla
si puede contener datos no compartibles. **No se envían resultados de bash**, el
entorno, la sesión completa ni reasoning. Se excluyen archivos ocultos, rutas
fuera del alcance y symlinks. Los campos no reconocidos provocan abstención.
Estas exclusiones no detectan secretos incrustados en archivos permitidos.

Objetivos, requisitos y argumentos también cuentan para el límite de bytes;
para Jev se incluye el cuerpo con las preguntas. Ante exceso se omite la consulta,
sin recortar información decisiva. El resumen de instrucciones de repositorio no
se infiere: los requisitos evaluables deben estar en la configuración y el objetivo.
Se registra el hash del system prompt observable, sin enviar su contenido.

Sin alcance, off sigue registrando IDs/métricas, pero no objetivos, argumentos ni
lecturas. Los directorios de revisiones usan permisos 0700 y archivos 0600.
No incluir claves en configuración ni consola.

## Política, fallos y límites

Preguntas `Choice` separadas por requisito/evidencia: contradicción, premisa
refutada, desviación y redundancia. No se mezclan en un score. La política valida
referencias y confianza; la redundancia requiere además lectura exacta, vigente
y disponible. `local` es deliberadamente conservador y solo compara lecturas;
Jev puede vetar esa hipótesis. Ningún juicio acredita por sí solo que un bloqueo
sea correcto. Las herramientas personalizadas quedan sin intervención.

Observación síncrona, plazo total de 1500 ms, cero reintentos, 100 consultas,
50000 tokens remotos observados y máximo de 16384 bytes por solicitud. El límite
de tokens se aplica **entre consultas** y puede excederse por una última respuesta;
si falta uso, se suspenden nuevas consultas. No equivale a un límite monetario:
la tarifa y el coste siguen `unknown`. Tres fallos consecutivos abren el circuito.
Los valores se pueden fijar en JSON antes de cada campaña.

Timeout, 429, respuesta inválida, falta de clave, red o fallo del journal permiten
continuar. La cancelación del usuario sigue cancelando. Respuestas tardías,
compaction, cambio de rama/sesión, aclaraciones y cambios de modo invalidan el
estado. Resume empieza sin historial. Tras resume, fork o compaction se requiere
`/jev task <objetivo completo>` para declarar el objetivo íntegro y salir de la
abstención por historial incompleto; una aclaración sola no reconstruye la tarea. No hay caché de juicios. Con herramientas
hermanas pendientes se abstiene; no inventa sus resultados. Bash y escrituras
invalidan evidencia previa. Se permite como máximo un bloqueo equivalente por
estado y cinco por sesión.

## Reportes y anotaciones

```bash
npm run report -- /ruta/events.jsonl
npm run report -- /ruta/events.jsonl --markdown
npm run annotate -- /ruta/events.jsonl REVIEW_ID justified 'Evidencia y motivo'
```

También se aceptan `false_positive` y `uncertain`. Las anotaciones son un JSONL
separado e inmutable por append; no reescriben decisiones. El reporte cuenta
propuestas, resultados observados, bloqueos, abstenciones, latencia acumulada y
uso remoto disponible. Latencia acumulada del revisor **no significa ahorro**.
El éxito final de los fixtures Pi aparece en `results.json`; la revisión humana
sigue siendo necesaria. Las revisiones declaran `unlinked` respecto a TraceStore;
los tests verifican IDs contra el JSONL de Pi, sin modificar trazas publicadas.

## Alcance del piloto

Implementa el switch, el circuito, la guardia de seguridad y el banco para
experimentar; no da por completada la campaña S6 del plan. Faltan calibración empírica, Gemma/Qwen end-to-end, tarifas,
intervalos estadísticos, anotación de todas las llamadas útiles y propuestas de
mejora del harness validadas en tareas reservadas. `repeated_failed_command` existe
como regla local; su versión semántica con Jev sigue pendiente de un adaptador de
resultados bash con autorización propia. Las pruebas
simuladas de contradicciones no acreditan la precisión del modelo remoto.

Referencias: [plan](../../../docs/plans/pi-jev-tool-utility-reviewer.md),
[SDK TypeSafe](https://docs.typesafe.ai/sdk/javascript.md) y documentación de Pi
0.85.1 incluida en la dependencia fijada.

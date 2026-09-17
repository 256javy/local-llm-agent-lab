# Plan: revisar la utilidad de herramientas de Pi con Jev

## Intención y estado

Plan ajustado el 2026-09-17. Solo describe trabajo futuro: no hay integración
implementada, envíos de sesiones a TypeSafe ni mejora de rendimiento demostrada.

El usuario inicia aquí un modelo local (Gemma 4 12B, Qwen 3.8 u otro), entra
en un repositorio de código, abre Pi, selecciona ese modelo y trabaja. Jev se
integrará en el harness de Pi para evaluar las acciones propuestas antes de
que se ejecuten, según la tarea vigente y la evidencia disponible. El objetivo
es evitar trabajo innecesario y acciones incorrectas, y ayudar al modelo a
replantear el siguiente paso. La seguridad es un beneficio secundario y conserva
sus controles independientes.

Hay dos resultados buscados, ambos parte del alcance:

1. **Mejor ejecución de tareas:** menos desvíos, acciones equivocadas, reintentos
   y correcciones humanas, manteniendo o aumentando el éxito y reduciendo el
   costo total cuando sea posible.
2. **Mejora del harness:** documentar cada bloqueo y su desenlace, revisar si
   estuvo justificado y usar los patrones confirmados para mejorar instrucciones,
   system prompt, contexto y descripciones de herramientas. Medir después si
   el modelo propone menos acciones equivocadas.

La versión anterior recogía la utilidad, pero concentraba la intervención en
lecturas redundantes y dejaba las ediciones como análisis exploratorio. Tampoco
concretaba el ciclo de mejora de instrucciones. Ese recorte no representa el
alcance deseado: `read`, `bash`, `edit` y `write` se incluyen desde el diseño.
La activación de bloqueos será gradual **por patrón de error validado**, sin
reducir el producto final a un filtro de lecturas.

## Objetivo e hipótesis

Jev puede detectar que una acción repite información vigente, se desvía de la
tarea, contradice un requisito explícito o depende de una premisa refutada por
los resultados disponibles. La falta de contexto, por sí sola, no demuestra
que una acción sea incorrecta. Jev tampoco garantiza la corrección completa
de un parche: tests y revisión del resultado siguen siendo necesarios.

El rendimiento se mide sobre tareas de desarrollo completas, no en tokens por
segundo ni contando herramientas evitadas. Explorar, releer tras un cambio y
verificar pueden ser necesarios. Se contabilizan la red, la inferencia remota,
la preparación del estado y la recuperación tras un bloqueo. También puede
haber una mejora de calidad con mayor tiempo: se informará como ese intercambio,
sin presentarlo como ahorro.

La evaluación incluirá al menos un perfil Gemma 4 12B y uno Qwen 3.8 disponibles
en el catálogo al ejecutar la campaña, registrando sus IDs exactos, cuantización,
runtime y configuración. No se presupone que todo fallo provenga del tamaño del
modelo. La integración será independiente del perfil seleccionado en Pi.

## Encaje en el proyecto y viabilidad

Pi se ejecuta en el host; este proyecto mantiene el runtime en Docker y su
contrato `http://127.0.0.1:18080/v1`. La extensión sería TypeScript, opt-in,
con dependencias propias y carga explícita para el experimento. No necesita
modificar perfiles, llama.cpp, Compose ni el endpoint local. No se instalaría
globalmente ni se activaría mediante descubrimiento automático por defecto.

La API externa añade una dependencia de red al flujo local. `TYPESAFE_API_KEY`
pertenece al proceso de Pi y es independiente de `LLM_LAB_API_KEY`; tener la
clave configurada no equivale a autorizar el envío de contenido del proyecto.

Evidencia verificada para esta revisión:

- El paquete instalado `@earendil-works/pi-coding-agent` declara versión
  **0.85.1**. Su documentación permite bloquear en `tool_call` mediante
  `{ block: true, reason }` y observar `tool_result`. No se necesita reescribir
  herramientas. Esto acredita la interfaz documentada, no una prueba funcional.
- En esa versión, las llamadas hermanas de un lote pasan por revisión previa
  secuencial y después pueden ejecutarse concurrentemente. Los resultados de
  sus hermanas no están garantizados durante `tool_call`.
- La documentación actual de TypeSafe ofrece preguntas tipadas y un SDK
  JavaScript/TypeScript. `Noul` devuelve probabilidad de sí, sin campo separado
  de confianza. No se debe interpretar esa probabilidad como garantía de éxito.
- El backlog aún tiene pendiente Pi end-to-end. I-08 e I-09 aportan captura;
  I-10 a I-12 todavía no constituyen un evaluador completo. El experimento
  necesitará anotación y comparación explícitas, inicialmente manuales.

Antes del prototipo se fijarán versión de Pi, SDK y modelo Jev disponible. No
se tomará `main` upstream como contrato de una versión instalada. Si solo hay
un alias mutable del modelo remoto, se registrará esa limitación y la fecha;
no se afirmará reproducibilidad exacta entre revisiones del servicio.

## Estado mínimo por decisión

Cada evaluación se vinculará a `sessionId`, rama activa de la sesión,
`toolCallId`, versión del objetivo y revisión del estado. El estado acotado
contendrá únicamente información disponible **antes** de ejecutar la llamada:

- Objetivo vigente, restricciones, instrucciones aplicables del repositorio
  y criterios de aceptación; una aclaración
  puede modificarlo sin borrar requisitos anteriores. Una síntesis inferida
  conservará su procedencia y referencias a los mensajes originales.
- Herramienta, argumentos y directorio efectivo. Para `read`, ruta, rango y
  límite; para las demás, solo los campos permitidos por el contrato de datos.
- Evidencia candidata seleccionada localmente: ID, resultado o extracto,
  rango cubierto, error/truncamiento, antigüedad y huella del recurso cuando
  pueda comprobarse. Ausencia de evidencia no significa ausencia de utilidad.
- Cambios conocidos, verificaciones pendientes y herramientas todavía en curso.
  Un resultado pendiente nunca se considera evidencia disponible.
- Cobertura del contexto: campos omitidos, límites alcanzados y si la evidencia
  anterior sigue disponible para Pi. No se requiere chain-of-thought.

La selección de evidencia y su costo forman parte del experimento. Se fijarán
límites de bytes, candidatos y consultas antes de cada campaña. Si un recorte
elimina información decisiva, el resultado será abstención, no un juicio
negativo sobre la llamada.

Invalidar decisiones y caché ante cambio de objetivo, archivo, rama de sesión,
compaction, recarga o estado no verificable. Las escrituras externas también
pueden volver obsoleta una lectura: una huella debe verificarse cerca de la
decisión; si no puede garantizarse suficiente vigencia, no bloquear. No basta
un TTL ni un hash de argumentos. Al reanudar, reconstruir solo la rama activa
o empezar sin historial y abstenerse hasta reunir evidencia.

## Juicios y política de aplicación

El código comprueba elegibilidad, vigencia y cobertura. Una lectura idéntica
puede detectarse localmente, pero solo es candidata a redundante si el recurso
no cambió, el rango está cubierto, el resultado fue satisfactorio y el agente
dispone todavía de esa información. Tests, polling y comandos repetidos tras
cambios no son redundantes por igualdad textual.

Para los casos semánticos se formularán preguntas estrechas sobre la acción y
referencias concretas, con instrucciones y criterios versionados:

| Juicio | Forma propuesta | Uso |
| --- | --- | --- |
| ¿La acción contribuye a un requisito o a una exploración/verificación necesaria? | `Choice`: contribuye, ajena al objetivo, no evaluable | Detectar desvíos; no castigar exploración razonable. |
| ¿Un resultado anterior cubre la información solicitada? | `Noul` por candidato | Detectar redundancia con evidencia vigente y todavía disponible para Pi. |
| ¿Existe un propósito pendiente de verificación o actualización? | `Noul` | Impedir un bloqueo por redundancia cuando corresponde verificar. |
| ¿La acción contradice este requisito explícito? | `Choice`: contradice, compatible, no evaluable, por requisito | Detectar comandos o cambios incompatibles con la tarea. |
| ¿Esta evidencia respalda o refuta la premisa necesaria para la acción? | `Choice`: respalda, refuta, insuficiente, no evaluable | Detectar acciones basadas en premisas refutadas; insuficiencia sola no bloquea. |

Las preguntas independientes comparten una consulta. No se combinan en un score
global ni se multiplican probabilidades suponiendo independencia. Los umbrales
se calibran por patrón y herramienta con datos separados de la prueba final.
`Noul` devuelve probabilidad de sí, sin confianza separada; `Choice` permite
examinar opción y confianza. Ninguno garantiza que el juicio sea verdadero.

El código selecciona candidatos y comprueba referencias. Para `bash`, evalúa
comando, cwd, propósito y resultados previos; no considera shell arbitrario
una lectura segura por una expresión regular. Comandos opacos, evidencia
truncada o dependencias no observadas producen abstención. Las herramientas
personalizadas quedan en observación hasta tener un adaptador de contexto.

| Modo | Comportamiento |
| --- | --- |
| `off` | Sin consultas ni bloqueo por utilidad. |
| `observe` | Registrar juicios y bloqueos propuestos sin alterar el flujo del agente. |
| `enforce` | Bloquear patrones habilitados por herramienta; los demás siguen en observación. |

Una política versionada identifica patrones como `redundant_read`,
`repeated_failed_command`, `task_conflict`, `refuted_precondition` y
`off_task_action`. Su activación exige evidencia evaluable y calibración propia;
`off_task_action` requiere especial atención a falsos positivos de exploración.
La ausencia de umbrales calibrados mantiene el patrón en observación.

Ejemplos de decisiones que deben formar parte del corpus:

| Situación previa a la acción | Decisión esperada |
| --- | --- |
| Releer el mismo rango vigente y disponible, sin propósito nuevo | Candidato a bloqueo por redundancia. |
| Repetir un comando fallido con la misma causa y sin cambios relevantes | Candidato a bloqueo con referencia al error anterior. |
| Añadir una dependencia cuando la tarea exige explícitamente no añadirlas | Candidato a bloqueo por contradicción del requisito. |
| Editar suponiendo una firma que la lectura vigente demuestra distinta | Candidato a bloqueo por premisa refutada. |
| Ejecutar tests después de cambiar código o explorar una dependencia relevante | Permitir. |
| Crear un archivo solicitado que aún no existe, sin lectura previa | Permitir; ausencia de lectura no implica error. |
| Cambiar un archivo aparentemente ajeno sin contexto suficiente | Abstenerse; no inventar una contradicción. |

El bloqueo vuelve a Pi con `{ block: true, reason }` para permitir que el modelo
replantee el paso. La razón se construye en código con categoría, requisito o
resultado citado y una indicación breve de qué reconsiderar. Por ejemplo:
“Esta acción añade una dependencia, pero el requisito R2 pide resolverlo sin
nuevas dependencias. Replantea el cambio respetando R2”. Jev emite juicios
tipados, no una explicación libre ni una herramienta alternativa. No se cambian
argumentos ni se presenta una llamada bloqueada como ejecutada.

Como límites iniciales del piloto, permitir un bloqueo por acción equivalente
en el mismo estado y cinco por tarea. Al insistir o alcanzar ese máximo, dejar
continuar, registrar el bypass y pasar el patrón a observación durante esa tarea.
Son límites de utilidad, no permisos para eludir controles de seguridad. El
usuario podrá cambiar de modo, desactivar el revisor o permitir una llamada.
Todos estos eventos se registran para distinguir recuperación de bypass.

## Latencia, fallos y concurrencia

La observación retrospectiva evalúa snapshots previos a cada llamada. La
observación en vivo debe declarar si espera a Jev o usa una cola acotada. Una
cola usa snapshots inmutables, descarta trabajo al saturarse y nunca aplica
juicios tardíos a llamadas posteriores; así evita incorporar resultados futuros.
La modalidad con espera permite medir el costo que tendría intervenir.

Antes de activar consultas se fijarán `deadlineMs`, máximo de consultas y
tokens/costo remoto por tarea, tamaño de cola y tolerancia a fallos. El plazo
incluye reintentos del SDK; inicialmente se propone desactivarlos en el camino
crítico. Timeout, 429, falta de clave, respuesta inválida o error de red dejan
continuar Pi y se registran como fallos del servicio, no como baja utilidad.
El handler debe capturar errores propios: en Pi, una excepción de `tool_call`
bloquea la herramienta, por lo que no basta con dejarla propagarse.
La cancelación del usuario sí se respeta: no se continúa una tarea cancelada.

Se cancelarán solicitudes al cerrar o cambiar de sesión cuando sea posible y
se descartarán respuestas cuyo estado ya no coincida. Un circuito de fallos
suspenderá consultas durante la tarea al superar el límite configurado. La
latencia se medirá también por lote, porque revisiones secuenciales pueden
acumular espera antes de ejecutar herramientas paralelas.

## Datos y trazabilidad

Antes de enviar contenido real se revisará un payload de ejemplo y se
habilitará explícitamente el alcance de datos para esa campaña/proyecto:
campos y rutas permitidos, fragmentos máximos, exclusiones, destino y condiciones
de conservación del proveedor. Si estas condiciones no pueden establecerse,
solo se usarán fixtures sintéticos o material autorizado para compartir.

No se enviarán por defecto sesiones completas, entorno, credenciales, archivos
`.env`, reasoning ni resultados arbitrarios de `bash`. La redacción heurística
existente no garantiza que un payload sea apto para compartir. Texto de archivos
y herramientas será evidencia no confiable, nunca instrucciones del revisor;
se incluirán casos con instrucciones incrustadas para comprobar esa separación.

Los registros permanecerán bajo `.local/`, ignorados por Git, con permisos
restrictivos. Cada decisión conservará esquema, IDs, snapshot autorizado o su
referencia inmutable, hashes de política/preguntas, modelo solicitado/devuelto,
respuestas tipadas, latencia, uso disponible, acción y razón de abstención/error.
No registrar la clave ni volcar payloads sensibles en consola.

Conteos y tiempos observados se separarán de cálculos, etiquetas humanas e
inferencias de Jev mediante las procedencias de `trace-analysis.md`. Los reviews
serán artefactos asociados; no modificarán el raw ni el normalizado publicado.
La vinculación con el JSONL de Pi debe probarse por IDs, sin emparejar solo por
texto. Promover una trace a case/eval seguirá siendo una acción explícita.

## Diseño de evaluación

Primero reunir un corpus con tareas de exploración, corrección, edición y
verificación, incluidas sesiones sin redundancia. Fijar repositorio inicial,
objetivo, criterios de aceptación, versiones, herramientas/extensiones activas,
perfil, sampling, contexto y límites. Validar Pi con el perfil elegido antes
de atribuir un fallo al revisor. Ejecutar variantes GPU secuencialmente.

Anotar llamadas como `useful`, `redundant`, `off_task`, `incorrect` o
`uncertain`, indicando evidencia, requisito, propósito y categoría de error.
Las etiquetas humanas no se derivan del juicio de Jev. Para evaluar
la decisión previa no se mostrará información futura; el resultado completo
se usa por separado para juzgar el éxito de la tarea. Dividir calibración y
prueba por tarea/sesión, evitando que llamadas casi idénticas crucen particiones.

Comparar tres brazos con ejecuciones completas y repetidas:

| Brazo | Qué permite determinar |
| --- | --- |
| A: Pi sin revisor | Resultado y costo de referencia. |
| B: reglas locales de redundancia | Beneficio alcanzable sin Jev. |
| C: mismas reglas más Jev | Aporte incremental de los juicios semánticos. |

La instrumentación de métricas será comparable entre brazos. Alternar el orden,
restaurar cada estado inicial en un entorno aislado y fijar condiciones de
warmup/caché. No restaurar destructivamente el checkout de trabajo. Un replay
retrospectivo estima calidad de clasificación; no demuestra qué habría hecho
Pi tras recibir un bloqueo ni permite sumar duraciones como ahorro real.

Registrar por tarea y por tipo de herramienta:

- Éxito según verificaciones y revisión humana, `pass|partial|fail|unknown`,
  correcciones necesarias y finalizaciones prematuras.
- Tiempo extremo a extremo de todas las ejecuciones, mediana/p95 cuando la
  muestra lo permita, dispersión y diferencias emparejadas entre brazos.
- Tokens locales y remotos por separado, costo remoto con tarifa/fecha o
  `unknown`, latencia del revisor y costo de preparar estado.
- Llamadas propuestas, ejecutadas y bloqueadas; reintentos, trabajo desplazado,
  abstenciones, fallos, cobertura elegible y utilización de caché.
- Falsos positivos: llamadas útiles que se habrían bloqueado / llamadas útiles
  etiquetadas; precisión del bloqueo: bloqueos justificados / propuestas de bloqueo
  etiquetadas. Informar denominadores y los casos inciertos por separado.

Antes de la prueba final completar un manifest con número de tareas y
repeticiones, métrica primaria, reducción mínima relevante, margen admisible
de éxito/correcciones, máximo de falsos positivos, presupuestos y regla de
parada. La sección de piloto propone valores iniciales; el manifest fijará los
valores efectivos antes de ejecutar, sin presentarlos como resultados.
Si la muestra no distingue beneficio de variación, el resultado es inconcluso.
C debe justificar su costo adicional frente a B, además de mejorar A.

## Ciclo de mejora del harness

Cada bloqueo es una hipótesis del revisor, no una etiqueta verdadera del modelo.
Registrar también llamadas permitidas y abstenciones para poder medir omisiones
y falsos positivos. El registro de una decisión tendrá como mínimo:

- `schemaVersion`, `reviewId`, `sessionId`, rama de sesión, `toolCallId`,
  `taskVersion`, `stateRevision`, cwd y perfil local observado o `unknown`.
- Acción propuesta, snapshot previo o referencia inmutable, `evidenceIds` y
  `requirementIds`; límites y datos ausentes; versiones/hashes de preguntas,
  política, extensión y contexto/instrucciones efectivamente observables.
- Modelo Jev solicitado/devuelto, respuestas tipadas, probabilidades/confianza
  aplicables, latencia, tokens/costo disponible, `allow|block|abstain`,
  `wouldBlock`, categoría y razón concreta enviada a Pi.
- Eventos posteriores enlazados: reformulación, reintento, ejecución, bypass,
  intervención humana y outcome. Si la relación causal no es observable,
  marcarla como inferida o desconocida.

La revisión humana añadirá `justified|false_positive|uncertain`, causa probable
(modelo, instrucciones ambiguas, contexto ausente, herramienta, política de Jev
u otro componente) y referencias. Las anotaciones y outcomes son artefactos
separados; no se reescribe la decisión original al conocer el resultado.

Al cerrar una sesión, un reporte local JSON/Markdown mostrará casos y patrones,
su frecuencia con denominador, recuperación y errores del propio revisor. Para
cada patrón confirmado se propondrá un cambio pequeño: aclarar una instrucción,
ajustar el system prompt, mejorar una descripción de herramienta o aportar
contexto faltante. La propuesta citará casos, versión anterior, cambio y prueba
de regresión. No se editará automáticamente el prompt desde juicios de Jev.

Validar las mejoras en tareas reservadas comparando un diseño de cuatro variantes:
harness original/mejorado, cada uno con Jev apagado/activo. Esto permite distinguir
la ayuda inmediata del revisor de una reducción real de errores propuestos por
el modelo. Conservar preguntas/política para esta comparación; si cambian,
registrarlo como experimento separado. Menos bloqueos puede significar peor
detección: medir errores propuestos y éxito, no solo el número de bloqueos.

## Implementación por entregables

Rutas y comandos de esta sección son **propuestos**, todavía no existen. El
paquete vivirá en `clients/pi/jev-reviewer/`, con TypeScript, `package.json`,
lockfile y dependencias fijadas. No requiere completar I-10 a I-12 para probar
el flujo; su formato se alineará con esas interfaces al implementarlas.

| Entregable | Trabajo concreto | Criterio de salida |
| --- | --- | --- |
| S1. Contratos y fixtures | `src/contracts.ts`, esquemas y `fixtures/`: estado, decisión, outcome y anotación; rúbrica y manifest piloto. Fijar Pi, SDK y Jev. | Fixtures sintéticos cubren las cuatro herramientas y errores/acciones útiles; esquema validable sin red. |
| S2. Extensión y contexto | `src/index.ts` registra eventos de Pi y comandos; `src/state.ts` mantiene objetivo, requisitos y evidencia de la rama activa. Carga explícita desde otro repo. | Smoke test con Pi y modelo local demuestra captura antes de ejecución, cwd correcto, IDs y funcionamiento de `off`/`observe`. |
| S3. Revisor y política | `src/questions.ts`, `src/jev-client.ts`, `src/policy.ts`: SDK `@typesafe-ai/sdk`, preguntas por patrón, timeout, validación, abstención y reglas locales. | Tests con cliente simulado y replay de snapshots; ningún error propio bloquea accidentalmente Pi. API real en campaña separada. |
| S4. Registro y reporte | `src/journal.ts`, `src/report.ts`: JSONL, snapshots, anotaciones y reporte con enlaces. Comandos npm `report` y `annotate`. | Una sesión permite reconstruir cada bloqueo propuesto/real y su seguimiento; reporte determinista, sin mutar trazas publicadas. |
| S5. Intervención y recuperación | Activar `enforce` por patrón/herramienta calibrados; razones concretas, bypass, límites y retorno a observación. | Una llamada bloqueada no se ejecuta; Pi recibe la razón y puede reformular. Casos útiles de control pasan. Cubrir al menos un patrón de comando y uno de edición, además de lecturas. |
| S6. Evaluación y primera mejora | Ejecutar A/B/C, revisar bloqueos y producir propuesta de instrucciones más experimento original/mejorado. | Informe con éxito, costo, falsos positivos y conclusión; al menos una propuesta trazable validada o descartada, sin afirmar mejoras inconclusas. |

S1 → S2 → S3 → S4 → S5 → S6. S4 debe estar operativo antes del primer bloqueo
real de S5. Si un patrón no supera la calibración, permanece en observación y
se documenta el resultado; no bloquea la entrega de los patrones que sí sirven.

### Flujo de uso previsto

El modelo continúa iniciándose con las herramientas actuales del laboratorio.
Desde el repositorio donde se realizará la tarea:

```bash
# Ejemplo futuro, después de implementar e instalar las dependencias del paquete.
cd /ruta/al/repositorio
pi -e /home/javy/projects/local-llm-agent-lab/clients/pi/jev-reviewer/src/index.ts
```

Seleccionar el modelo local como hasta ahora. Proponer `/jev status`,
`/jev mode off|observe|enforce` y `/jev allow-once <review-id>` como controles
de la extensión. El modo inicial será `observe`, con configuración explícita
del proyecto y del alcance de datos. `allow-once` solo aplica al reintento de
la acción y estado referenciados; no reutiliza una autorización obsoleta.

La configuración externa del revisor contendrá `mode`, `model`,
`enabledPatterns`, `thresholds`, `deadlineMs`, `maxCallsPerTask`,
`maxInputBytes`, `maxBlocksPerTask`, alcance de datos y `storageRoot` absoluto.
No guardar la clave allí. Los artefactos se escribirán bajo
`/home/javy/projects/local-llm-agent-lab/.local/jev-reviews/<session-id>/`,
independientemente del cwd de Pi. Particionar también por rama de sesión y
vincular con `TraceStore` por IDs verificados; si la vinculación falta, declarar
`unlinked`, sin modificar raw ni eventos normalizados.

### Piloto y validación

Punto de partida propuesto: 24 tareas (exploración, corrección, edición y
verificación), 12 para calibrar y 12 reservadas para evaluar; ambos perfiles y
tres repeticiones por brazo A/B/C. Ejecutar primero un smoke por perfil y ampliar
solo si funciona la integración. Restaurar fixtures en directorios aislados,
serializar GPU y registrar ejecuciones pesadas en `docs/BACKLOG.md`.

Usar inicialmente observación síncrona para medir el costo real del camino de
intervención. Presupuestos iniciales ajustables antes de la evaluación:
`deadlineMs=1500`, cero reintentos, `maxCallsPerTask=100`,
`maxInputBytes=16384`, cinco bloqueos y circuito abierto tras tres fallos
consecutivos. El deadline limita toda la consulta; verificar su implementación
y cancelación contra el SDK elegido. No son promesas de latencia del servicio.
Fijar además un límite de gasto remoto en el manifest antes de la campaña real.

Para habilitar un patrón, exigir inicialmente precisión de bloqueo ≥95% y
falsos positivos ≤2% sobre casos etiquetados reservados para validación de la
calibración, con al menos 20 propuestas de bloqueo y 50 llamadas útiles por
patrón; ampliar el corpus si no alcanza. Informar intervalos y denominadores:
ese mínimo no demuestra tasas poblacionales. No usar las 12 tareas finales
para escoger umbrales. Mantener en observación los patrones sin evidencia.

Métrica principal: éxito verificado por tarea; reportar calidad y eficiencia
por separado. Para declarar mejora de eficiencia en el piloto, proponer al
menos 10% menos tiempo mediano emparejado, sin reducir éxito ni aumentar
correcciones humanas frente a A; C debe justificar su costo frente a B. Si la
incertidumbre impide sostenerlo, resultado inconcluso. Detener la intervención
ante un falso positivo que impida completar una tarea o un bucle de bloqueos.
Estos valores son criterios iniciales del plan, no resultados obtenidos.

Tests del paquete: política con respuestas simuladas, contratos, journal y
reporte, deadlines y lifecycle. Incluir archivo cambiado externa/internamente,
rango diferente, truncamiento, error previo, verificación necesaria, compaction,
cambio de objetivo, fork/resume, lote paralelo, reintento, timeout/429,
cancelación y exclusión de datos. Probar que el handler no altera argumentos y
que una respuesta tardía no bloquea otra llamada. Añadir integración real con
Pi para el circuito propuesta → bloqueo → reformulación → resultado.

Al implementar, ejecutar los tests/typecheck del paquete y las validaciones
prescritas en `AGENTS.md`; API real, descargas y benchmarks serán ejecuciones
explícitas y registradas. Esta revisión documental no instala ni activa nada.

## Referencias

- [Arquitectura](../architecture.md), [backlog](../BACKLOG.md),
  [benchmarking](../benchmarking.md) y [análisis de trazas](../trace-analysis.md).
- [Extensiones de Pi](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/extensions.md).
  Interfaz contrastada con `docs/extensions.md` del paquete instalado 0.85.1.
- [SDK JavaScript de TypeSafe](https://docs.typesafe.ai/sdk/javascript.md),
  [Noul](https://docs.typesafe.ai/primitives/noul.md) y
  [confianza](https://docs.typesafe.ai/confidence.md), consultados el 2026-09-17.
- [Verificación de citas](https://docs.typesafe.ai/cookbooks/citation_check.md):
  referencia de composición entre reglas y juicio semántico; sus umbrales y
  resultados no se trasladan a este experimento.

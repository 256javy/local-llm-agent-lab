# Intención: revisar la utilidad de herramientas de Pi con Jev

## Estado

Propuesta documental. No hay integración implementada ni resultados que permitan
afirmar una mejora de rendimiento.

## Objetivo e hipótesis

Evaluar si Jev puede ayudar a Pi, cuando usa un modelo local pequeño como Qwen
3.8, a evitar pasos que no acercan la sesión a la tarea: lecturas y búsquedas
repetidas, comandos sin propósito nuevo y ediciones prematuras o redundantes.

La hipótesis es que una revisión breve de la siguiente llamada a herramienta,
basada en la tarea y en la evidencia ya obtenida, puede reducir trabajo total
sin perjudicar la corrección. Menos llamadas por sí solas no prueban la hipótesis:
la consulta a Jev también consume tiempo y una llamada detenida puede provocar
reintentos o privar al agente de información necesaria.

## Ubicación y alcance previstos

Pi ejecuta en el host y el modelo local sigue servido por este proyecto. La
integración prevista pertenece a una extensión opt-in de Pi que observa sus
eventos de herramientas; no requiere modificar perfiles, llama.cpp ni el
endpoint local. La credencial de TypeSafe pertenece al proceso de Pi mediante
`TYPESAFE_API_KEY`, separada de `LLM_LAB_API_KEY`.

El primer alcance comprende `read`, `bash`, `edit` y `write`. El juicio buscado
es **utilidad para la tarea**, no revisión de seguridad ni calificación general
del trabajo. La seguridad y los permisos conservan sus propios controles.

## Decisión propuesta por llamada

La extensión construiría un estado acotado con:

- objetivo vigente del usuario y contexto indispensable para interpretarlo;
- herramienta y argumentos propuestos;
- archivos, búsquedas y resultados recientes relevantes;
- cambios ya realizados y evidencia pendiente para el siguiente paso.

Jev respondería preguntas estrechas y tipadas: si la llamada probablemente
aporta información nueva, si repite trabajo disponible y, para una edición, si
existe evidencia suficiente para hacerla ahora. El código decidiría cómo usar
esas respuestas. Una repetición exacta detectable localmente no necesita una
consulta externa. Una respuesta incierta no debe convertirse automáticamente
en un bloqueo.

Si una llamada se detiene, Pi debe recibir una explicación concreta que permita
replantear el paso, por ejemplo qué resultado anterior ya responde la búsqueda.
El revisor no elige ni ejecuta una herramienta alternativa por cuenta propia.

## Evaluación antes de intervenir

1. Ejecutar primero en modo observación: registrar la decisión propuesta sin
   alterar las llamadas de Pi.
2. Reunir tareas representativas y revisar manualmente falsos positivos,
   especialmente lecturas necesarias y ediciones bien fundadas.
3. Comparar ejecuciones equivalentes con y sin revisión usando el mismo perfil,
   tarea, estado inicial y criterios de resultado. Registrar la variación entre
   ejecuciones.
4. Medir éxito de la tarea, tiempo extremo a extremo, tokens locales, llamadas
   por tipo, repeticiones, consultas y latencia de Jev, reintentos y pasos útiles
   detenidos. Distinguir llamadas evitadas de trabajo desplazado a pasos
   posteriores.
5. Considerar bloqueos únicamente para patrones con evidencia de beneficio y
   baja tasa de falsos positivos. Repetir la comparación tras activarlos.

La mejora se aceptaría solo si se conserva o aumenta el éxito de las tareas y
disminuye el costo total relevante para el usuario. Los umbrales y el conjunto
de tareas deben fijarse antes de interpretar los resultados; esta propuesta no
asume números de mejora.

## Límites y datos

Enviar argumentos de herramientas o resultados a TypeSafe puede revelar código,
rutas y otros datos del proyecto. La selección de campos y la exclusión de
secretos necesitan un contrato explícito antes de cualquier envío automático.
La redacción heurística de trazas existente no garantiza que un dato sea seguro
para compartir. Los registros de evaluación deben permanecer locales e ignorados
por Git, salvo fixtures sintéticos.

La extensión debe definir un plazo máximo para Jev y un comportamiento claro
ante errores o falta de credencial. Durante la evaluación, una falla de Jev no
debe interrumpir la tarea ni presentarse como un juicio sobre su utilidad.

## Referencias del proyecto

- [Benchmarking](../benchmarking.md): separa rendimiento de inferencia, harness
  HTTP y trabajo real.
- [Análisis de trazas](../trace-analysis.md): procedencia, privacidad y
  promoción de sesiones reales a casos comparables.

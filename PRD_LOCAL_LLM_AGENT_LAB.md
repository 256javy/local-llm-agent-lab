# PRD y especificación técnica: Local LLM Agent Lab

## 1. Identidad del proyecto

- **Nombre recomendado del repositorio:** `local-llm-agent-lab`
- **Nombre de producto interno:** Local LLM Agent Lab
- **Repositorio de origen conceptual:** este documento nace del experimento `qwen`, pero el proyecto nuevo debe comenzar desde un repositorio limpio.
- **Estado:** propuesta para implementación en una sesión nueva.
- **Puerto HTTP predeterminado:** `127.0.0.1:18080`.
- **Licencia sugerida:** MIT para el código propio, manteniendo un registro separado de licencias y términos de modelos, runtimes e imágenes.

### Nombres alternativos

1. `local-llm-agent-lab` — recomendado; describe inferencia local, agentes y experimentación.
2. `local-ai-agent-runtime` — enfatiza operación estable más que investigación.
3. `local-llm-runtime-lab` — adecuado si los agentes terminan siendo consumidores secundarios.
4. `local-agent-model-hub` — comunica catálogo y selección, pero puede confundirse con un repositorio de modelos.

## 2. Resumen ejecutivo

Local LLM Agent Lab será un stack local y extensible para descargar, preparar, ejecutar, detener, cambiar y comparar modelos de lenguaje en una GPU NVIDIA. Expondrá un endpoint estable compatible con OpenAI para que clientes instalados en el host, inicialmente Pi Coding Agent y OpenCode, puedan operar directamente sobre el directorio actual del usuario sin bind mounts por proyecto.

La inferencia se ejecutará dentro de contenedores. Los agentes y sus herramientas se ejecutarán en el host. El sistema cargará un solo modelo principal a la vez y liberará la VRAM antes de activar otro perfil. El diseño deberá admitir múltiples runtimes y formatos en el futuro, sin esconder las diferencias técnicas que influyen en rendimiento, compatibilidad o calidad.

La primera versión ofrecerá dos perfiles validados:

- Qwen 3.6 35B-A3B MoE, cuantizado para 16 GB, con llama.cpp compatible con MTP/NextN.
- Gemma 4 12B IT QAT `UD-Q4_K_XL`, con drafter MTP, orientado a alta velocidad, tool calling y contexto amplio.

Gemma 4 26B-A4B se incorporará como perfil experimental de mayor calidad y menor margen de VRAM. Qwen y Gemma nunca se cargarán simultáneamente.

## 3. Problema

El experimento actual combina en un mismo contenedor el agente, el runtime, el modelo, SSH y un workspace montado. Ese enfoque sirve para pruebas aisladas, pero genera fricción para uso cotidiano:

- El agente solo conoce el workspace montado en el contenedor.
- Cambiar de proyecto requiere recrear mounts o copiar archivos.
- Herramientas, credenciales y configuración del host deben duplicarse dentro del contenedor.
- El runtime administrado por una extensión puede usar puertos efímeros y un ciclo de vida ligado a un único cliente.
- Pi y OpenCode no pueden compartir limpiamente el mismo servicio de inferencia.
- Cambiar entre modelos, cuantizaciones o runtimes carece de un contrato común.
- No existe un mecanismo reproducible de benchmark y comparación.

## 4. Visión

Desde cualquier repositorio local, el usuario debe poder ejecutar:

```bash
cd ~/projects/mi-proyecto
pi --model local-lab/qwen-3.6-moe-2bit
```

o:

```bash
cd ~/projects/mi-proyecto
opencode
```

El cliente utilizará el directorio actual y sus herramientas locales, mientras el modelo activo responderá a través de:

```text
http://127.0.0.1:18080/v1
```

El operador podrá cambiar el modelo sin editar Compose ni conocer los comandos internos del runtime:

```bash
llm-lab start qwen-3.6-moe-2bit
llm-lab switch gemma-4-12b-qat-mtp
llm-lab status
llm-lab stop
```

## 5. Objetivos

### 5.1 Objetivos de producto

- Ejecutar agentes en el host y modelos en contenedores.
- Permitir que el agente trabaje en cualquier `$PWD` sin bind mounts por proyecto.
- Ofrecer un endpoint local estable para múltiples clientes compatibles con OpenAI.
- Seleccionar y cambiar perfiles de modelo mediante una CLI uniforme.
- Garantizar que solo un perfil consumidor de GPU esté activo por defecto.
- Persistir modelos, builds y caches sin incluirlos en Git.
- Hacer reproducibles la configuración y los benchmarks.
- Facilitar la incorporación futura de modelos, cuantizaciones, drafters y runtimes.
- Proporcionar diagnósticos claros de Docker, NVIDIA, VRAM, salud del servidor y compatibilidad.

### 5.2 Objetivos técnicos

- Aislar el plano de control del runtime de inferencia.
- Mantener metadatos declarativos por perfil.
- Evitar que los clientes conozcan rutas internas, puertos efímeros o argumentos específicos de cada runtime.
- Soportar inicialmente `llama-server`; diseñar adaptadores para LiteRT-LM y otros servidores.
- Escuchar exclusivamente en loopback de forma predeterminada.
- Hacer que inicio, cambio y detención sean operaciones idempotentes.
- Verificar liberación de VRAM antes de cargar otro modelo.
- Publicar estado legible por humanos y JSON para automatizaciones.

## 6. No objetivos iniciales

- Ejecutar Pi u OpenCode dentro del contenedor.
- Montar automáticamente todos los proyectos del usuario.
- Ejecutar dos modelos grandes simultáneamente.
- Distribuir inferencia entre varias máquinas.
- Exponer el endpoint a la LAN o Internet por defecto.
- Administrar secretos de terceros más allá de referencias a variables locales.
- Entrenar o ajustar modelos en la primera versión.
- Proporcionar una interfaz web propia en el MVP.
- Reemplazar las funciones de Pi, OpenCode, Ollama o LM Studio como clientes.
- Descargar modelos sin una acción explícita del usuario.

## 7. Usuarios y casos de uso

### 7.1 Usuario principal

Desarrollador Linux con una GPU NVIDIA RTX 5060 Ti de 16 GB, Docker Compose, Pi y OpenCode instalados en el host. Trabaja en múltiples repositorios y necesita inferencia privada local con herramientas de programación.

### 7.2 Casos de uso prioritarios

1. Activar Qwen para tareas agentic complejas.
2. Activar Gemma 4 12B para respuestas rápidas, programación y tool calling.
3. Cambiar entre Qwen y Gemma liberando la VRAM entre perfiles.
4. Usar el mismo endpoint desde Pi y OpenCode, aunque no necesariamente al mismo tiempo.
5. Ejecutar benchmarks comparables de prompt processing, decode, TTFT, VRAM y tool calling.
6. Incorporar un modelo nuevo mediante un manifiesto y un adaptador existente.
7. Diagnosticar rápidamente problemas de driver, Docker, CUDA, descarga, compilación o salud.

## 8. Principios de diseño

1. **Agente en host, inferencia en contenedor.** El agente conserva acceso natural al proyecto y a las herramientas instaladas.
2. **Un modelo principal a la vez.** La selección representa estado exclusivo, no una colección de servicios concurrentes.
3. **Endpoint estable, runtime reemplazable.** Los clientes usan `127.0.0.1:18080`; los detalles internos pertenecen al stack.
4. **Perfiles declarativos.** Modelo, cuantización, runtime, contexto, cache KV, MTP y requisitos deben estar versionados.
5. **Descargas y builds fuera de Git.** Los manifiestos se versionan; los artefactos pesados se almacenan en volúmenes o directorios ignorados.
6. **Compatibilidad explícita.** Un runtime compatible con OpenAI no se considerará automáticamente compatible con tool calling, reasoning o multimodalidad.
7. **Medir antes de declarar óptimo.** Las recomendaciones por defecto deben derivar de benchmarks reproducibles en el hardware objetivo.
8. **Seguridad local predeterminada.** Loopback, sin exposición externa y con claves opcionales incluso para uso local.

## 9. Arquitectura propuesta

```text
┌─────────────────────────────────────────────────────────────┐
│ Host Linux                                                  │
│                                                             │
│  proyecto A/$ pi          proyecto B/$ opencode             │
│          │                         │                         │
│          └──────────┬──────────────┘                         │
│                     │ OpenAI-compatible HTTP                │
│                     ▼                                       │
│           127.0.0.1:18080/v1                               │
│                     │                                       │
│             Local LLM Agent Lab CLI                         │
│                     │                                       │
│  ┌──────────────────▼────────────────────────────────────┐   │
│  │ Docker                                                │   │
│  │                                                       │   │
│  │  perfil activo único                                  │   │
│  │  llama-server / futuro adaptador LiteRT-LM            │   │
│  │         │                                             │   │
│  │         ├── modelo principal                          │   │
│  │         ├── drafter MTP opcional                      │   │
│  │         ├── cache Hugging Face/modelos                │   │
│  │         └── GPU NVIDIA                                │   │
│  └───────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 9.1 Componentes

- **CLI `llm-lab`:** interfaz del operador y plano de control.
- **Registro de perfiles:** manifiestos versionados y validables.
- **Adaptador de runtime:** traduce el manifiesto a Compose y argumentos concretos.
- **Servicio de inferencia:** inicialmente `llama-server` con CUDA.
- **Almacenamiento persistente:** modelos, fuentes, builds, caches y resultados.
- **Health gate:** espera que `/health` y `/v1/models` confirmen disponibilidad.
- **Benchmark harness:** ejecuta escenarios fijos y guarda resultados estructurados.
- **Configuración de clientes:** plantillas para Pi y OpenCode.

## 10. Puerto y red

### 10.1 Contrato predeterminado

- API: `127.0.0.1:18080`.
- URL base: `http://127.0.0.1:18080/v1`.
- Bind del contenedor: `0.0.0.0:<puerto-interno>` solo dentro de su namespace.
- Publicación Docker: `127.0.0.1:18080:<puerto-interno>`.
- Nunca publicar `0.0.0.0:18080` por defecto.

### 10.2 Configurabilidad

```env
LLM_LAB_HOST=127.0.0.1
LLM_LAB_PORT=18080
```

La CLI debe rechazar puertos ocupados con un diagnóstico que identifique el proceso cuando sea posible. Los benchmarks paralelos o comparativos podrán reservar `18100-18199`, pero el MVP ejecutará pruebas secuenciales para no competir por VRAM.

## 11. Registro de perfiles

Cada perfil debe declarar al menos:

```yaml
id: gemma-4-12b-qat-mtp
display_name: Gemma 4 12B IT QAT with MTP
runtime: llama-cpp-mtp
model:
  source: huggingface
  repository: unsloth/gemma-4-12B-it-qat-GGUF
  artifact: gemma-4-12B-it-qat-UD-Q4_K_XL.gguf
  revision: null
draft_model:
  repository: google/gemma-4-12B-it-qat-q4_0-unquantized-assistant
  artifact: mtp-gemma-4-12B-it.gguf
server:
  context_size: 65536
  parallel: 1
  flash_attention: true
  cache_type_k: q8_0
  cache_type_v: q8_0
  jinja: true
  reasoning: configurable
  extra_args:
    - --spec-type
    - draft-mtp
    - --spec-draft-n-max
    - "2"
requirements:
  min_vram_gib: 12
  recommended_vram_gib: 16
capabilities:
  chat_completions: true
  responses: verify
  tool_calling: verify
  vision: deferred
  audio: deferred
  reasoning: true
status: experimental
```

El esquema definitivo deberá validar tipos, campos obligatorios, identificadores únicos, revisiones opcionales, checksums y capacidades conocidas.

## 12. Perfiles iniciales

### 12.1 `qwen-3.6-moe-2bit`

- Arquitectura: Qwen 3.6 35B-A3B MoE.
- Cuantización: 2-bit orientada a 16 GB.
- Runtime: snapshot o fork de llama.cpp con MTP/NextN requerido por el artefacto.
- Contexto inicial: 131.072 solo si las mediciones de VRAM lo permiten; reducir de forma documentada si no.
- KV cache inicial: `q4_0` para K y V.
- Flash Attention: habilitado.
- GPU layers: autoajuste o valor derivado de benchmark.
- Estado inicial: experimental hasta completar tool-calling y benchmark agentic.

### 12.2 `gemma-4-12b-qat-mtp`

- Arquitectura: Gemma 4 12B IT.
- Cuantización objetivo: QAT `UD-Q4_K_XL`.
- Drafter: MTP Q4_0 compatible.
- Runtime: llama.cpp con soporte Gemma 4 MTP.
- Contexto predeterminado: 65.536.
- KV cache: `q8_0` para conservar VRAM.
- `parallel`: 1.
- `spec-draft-n-max`: 2 como valor inicial, sujeto a benchmark local.
- Estado inicial: recomendado después de validar calidad y tool calling.

### 12.3 `gemma-4-26b-a4b-quality`

- Arquitectura: Gemma 4 26B-A4B MoE.
- Objetivo: máxima capacidad razonable en 16 GB.
- Cuantización candidata: `UD-Q3_K_M`, `UD-IQ4_XS` u oficial QAT Q4_0 si existe margen real.
- Contexto: determinado por benchmark; no prometer 256K.
- Multimodalidad: deshabilitada inicialmente para reservar VRAM.
- MTP: diferido hasta comprobar que el modelo principal, drafter, KV cache y buffers caben completamente.
- Estado: experimental; no será el perfil predeterminado del MVP.

## 13. Runtimes

### 13.1 llama.cpp / llama-server

Runtime principal del MVP por:

- Backend CUDA maduro para NVIDIA.
- Soporte GGUF y cuantizaciones variadas.
- API compatible con OpenAI.
- Flash Attention, KV cache cuantizada y offload configurable.
- MTP y speculative decoding disponibles o integrables mediante snapshots fijados.
- Diagnóstico y benchmark de bajo nivel.

Cada imagen o build debe estar fijado a una revisión reproducible. `latest` podrá existir solo como canal de prueba, nunca como base silenciosa del perfil estable.

### 13.2 LiteRT-LM

Adaptador posterior al MVP, inicialmente para Gemma 4:

- Formato `.litertlm` separado de GGUF.
- Backend GPU de escritorio.
- MTP integrado.
- Servidor compatible con OpenAI disponible.
- Interés especial para comparar velocidad, memoria, tool calling y multimodalidad.

No se declarará superior a llama.cpp en NVIDIA hasta completar una comparación local con el mismo modelo, contexto, prompt, sampling y capacidades.

### 13.3 Otros runtimes futuros

- Ollama como adaptador de conveniencia y línea base.
- vLLM o SGLang para hardware con más VRAM o concurrencia.
- TensorRT-LLM cuando exista una ruta mantenible para los modelos objetivo.
- MLX solo para hosts Apple.

## 14. CLI requerida

### 14.1 Comandos MVP

```text
llm-lab doctor
llm-lab profiles
llm-lab pull <profile>
llm-lab start <profile>
llm-lab stop
llm-lab switch <profile>
llm-lab status [--json]
llm-lab logs [--follow]
llm-lab health [--json]
llm-lab benchmark <profile> [--suite smoke|agent|performance]
llm-lab client-config pi
llm-lab client-config opencode
llm-lab help
```

### 14.2 Semántica

- `doctor`: solo lectura; comprueba Docker, Compose, driver, acceso GPU, puertos, disco y herramientas.
- `profiles`: lista perfiles, estado, requisitos y disponibilidad local.
- `pull`: descarga artefactos sin iniciar el servidor.
- `start`: falla si hay otro perfil activo, salvo que coincida; debe sugerir `switch`.
- `switch`: detiene el activo, confirma liberación, inicia el solicitado y espera salud.
- `stop`: idempotente y no elimina caches.
- `status`: indica perfil, PID/contenedor, endpoint, salud, uptime y VRAM.
- `benchmark`: guarda entorno, revisión, argumentos y resultados.
- `client-config`: imprime o genera una plantilla; no sobrescribe configuración existente sin confirmación.

### 14.3 Códigos de salida

- `0`: operación exitosa.
- `1`: fallo operativo general.
- `2`: argumentos o perfil inválidos.
- `3`: requisito del host no satisfecho.
- `4`: conflicto de puerto o proceso.
- `5`: fallo de descarga o integridad.
- `6`: servidor iniciado pero no saludable.
- `7`: VRAM no liberada o insuficiente.

## 15. Ciclo de vida y exclusión de GPU

`switch` debe implementar esta máquina de estados:

```text
IDLE
  └── start ──> PREPARING ──> STARTING ──> HEALTHY
HEALTHY
  └── switch ─> STOPPING ──> VERIFYING_RELEASE ──> STARTING ──> HEALTHY
HEALTHY
  └── stop ───> STOPPING ──> VERIFYING_RELEASE ──> IDLE
```

Requisitos:

- Lock local para evitar dos operaciones concurrentes.
- Archivo de estado atómico con perfil, runtime, contenedor y timestamps.
- Timeout configurable de detención e inicio.
- Verificación mediante Docker y `nvidia-smi`.
- Si la VRAM no se libera, no iniciar el siguiente perfil.
- No matar procesos GPU ajenos al proyecto.
- Mostrar los procesos que impiden continuar y solicitar acción explícita.

## 16. Almacenamiento

### 16.1 Directorios sugeridos

```text
local-llm-agent-lab/
├── AGENTS.md
├── README.md
├── LICENSE
├── compose.yaml
├── .env.example
├── bin/
│   └── llm-lab
├── config/
│   ├── profiles/
│   └── schemas/
├── docker/
│   ├── llama-cpp/
│   └── litert-lm/
├── clients/
│   ├── pi/
│   └── opencode/
├── benchmarks/
│   ├── prompts/
│   ├── suites/
│   └── schemas/
├── scripts/
├── tests/
└── docs/
    ├── architecture.md
    ├── adding-models.md
    ├── benchmarking.md
    ├── operations.md
    └── decisions/
```

### 16.2 Datos persistentes fuera de Git

- Modelos GGUF y `.litertlm`.
- Fuentes y builds de runtimes.
- Cache de Hugging Face.
- Logs de ejecución voluminosos.
- Resultados locales no seleccionados para documentación.
- Estado y locks.
- Credenciales y tokens.

Se debe permitir elegir entre volúmenes Docker y rutas del host. El valor predeterminado debería usar un directorio explícito, por ejemplo `${XDG_DATA_HOME:-$HOME/.local/share}/local-llm-agent-lab`, para que el usuario pueda inspeccionar, respaldar y limpiar artefactos conscientemente.

## 17. Integración con clientes

### 17.1 Pi Coding Agent

Generar una entrada para `~/.pi/agent/models.json` con:

- `baseUrl`: `http://127.0.0.1:18080/v1`.
- API: `openai-completions` inicialmente.
- Identificadores de modelo estables del laboratorio.
- Flags de compatibilidad por perfil.
- Límites de contexto y salida coherentes con el perfil activo.

Pi se instalará y ejecutará en el host. El proyecto no administrará sus sesiones ni credenciales.

### 17.2 OpenCode

Generar una entrada global para el proveedor `local-lab` usando el paquete OpenAI-compatible y la misma URL base. La herramienta debe preservar proveedores existentes y no asumir que el archivo es JSON estricto si el usuario usa JSONC.

### 17.3 Contrato de identificadores

Los clientes deben poder usar identificadores estables como:

```text
local-lab/qwen-3.6-moe-2bit
local-lab/gemma-4-12b-qat-mtp
local-lab/gemma-4-26b-a4b-quality
```

Si el servidor solo publica el modelo activo, una solicitud a un identificador inactivo deberá fallar claramente; la primera versión no cambiará perfiles automáticamente como efecto lateral de una petición HTTP.

## 18. API y compatibilidad

### 18.1 Endpoints mínimos

- `GET /health` o equivalente normalizado.
- `GET /v1/models`.
- `POST /v1/chat/completions` con streaming.
- Tool calling compatible con el cliente seleccionado.

### 18.2 Endpoints deseables

- `POST /v1/responses`.
- Métricas Prometheus en un puerto interno o ruta separada.
- Endpoint del plano de control solo si una CLI local deja de ser suficiente.

### 18.3 Matriz de capacidades

Cada perfil debe registrar y probar por separado:

- Chat básico.
- Streaming.
- System/developer role.
- Tool definitions.
- Tool call serial y paralelo.
- Resultados de herramientas.
- JSON schema o structured output.
- Thinking/reasoning.
- Visión.
- Audio.
- Contexto máximo verificado.

No se debe inferir una capacidad a partir de otra.

## 19. Benchmarking

### 19.1 Principios

- Comparar el mismo modelo y cuantización al evaluar runtimes.
- Comparar perfiles completos al evaluar experiencia de usuario.
- Registrar temperatura, seed, contexto, batch, ubatch, KV cache y revisión.
- Ejecutar calentamiento antes de medir.
- Medir múltiples repeticiones y reportar mediana y dispersión.
- Separar prefill, TTFT, decode y tiempo total.
- Registrar VRAM pico, RAM, potencia y versión del driver cuando sea viable.

### 19.2 Suites

#### Smoke

- Salud.
- Lista de modelos.
- Chat no streaming.
- Chat streaming.
- Tool call simple.
- Contexto corto.

#### Performance

- Prompt de 512, 2K, 8K, 32K y 64K tokens cuando aplique.
- Generación fija de 256 y 1.024 tokens.
- MTP desactivado y valores 1, 2 y 4.
- KV `f16`, `q8_0` y `q4_0` si están soportadas.
- Arranque frío y caliente.

#### Agent

- Inspección de repositorio.
- Edición pequeña con tool calling.
- Ejecución de prueba y corrección.
- Resumen de diff.
- Tarea de varios pasos con al menos tres herramientas.
- Registro de completitud, llamadas inválidas, loops y tiempo total.

### 19.3 Formato de resultados

Guardar JSON versionado con:

- Hardware y sistema.
- Perfil y hashes.
- Runtime y revisión.
- Argumentos efectivos.
- Prompt o identificador de fixture.
- Métricas crudas.
- Resumen calculado.
- Resultado funcional.

Los informes Markdown deben generarse a partir del JSON, no ser la única fuente.

## 20. Seguridad y privacidad

- Escuchar en loopback de forma predeterminada.
- No incluir tokens de Hugging Face, claves o credenciales en Git.
- Permitir una API key local opcional.
- No montar el home completo dentro del contenedor.
- Montar únicamente almacenamiento de modelos y runtime necesario.
- Ejecutar el contenedor sin privilegios y sin `--privileged`.
- Exponer únicamente los dispositivos NVIDIA requeridos.
- Fijar imágenes por digest o versión cuando el perfil pase a estable.
- Verificar checksums de modelos cuando estén disponibles.
- Documentar que los modelos y extensiones tienen licencias y riesgos propios.
- No borrar modelos, caches o volúmenes mediante `stop` o `switch`.

## 21. Observabilidad y diagnóstico

`llm-lab doctor` debe mostrar:

- Versión de Docker y Compose.
- GPU, compute capability, VRAM y driver.
- Acceso a GPU desde un contenedor de prueba.
- Compatibilidad mínima del driver con la imagen seleccionada.
- Estado del puerto 18080.
- Espacio disponible en disco y tamaño de caches.
- Perfil activo y salud.
- Procesos que usan VRAM, sin terminarlos.

`llm-lab status --json` debe ser estable para scripts y contener:

```json
{
  "state": "healthy",
  "profile": "gemma-4-12b-qat-mtp",
  "endpoint": "http://127.0.0.1:18080/v1",
  "runtime": "llama-cpp-mtp",
  "container": "local-llm-agent-lab-server",
  "uptimeSeconds": 120,
  "gpu": {
    "name": "NVIDIA GeForce RTX 5060 Ti",
    "vramUsedMiB": 0,
    "vramTotalMiB": 16303
  }
}
```

## 22. Configuración

### 22.1 `.env.example`

Debe cubrir solo valores operativos y no duplicar detalles propios de los perfiles:

```env
LLM_LAB_HOST=127.0.0.1
LLM_LAB_PORT=18080
LLM_LAB_DATA_DIR=
LLM_LAB_DEFAULT_PROFILE=gemma-4-12b-qat-mtp
LLM_LAB_API_KEY=
NVIDIA_VISIBLE_DEVICES=all
NVIDIA_DRIVER_CAPABILITIES=compute,utility
HF_TOKEN=
```

### 22.2 Precedencia

1. Flags de CLI.
2. Variables de entorno.
3. `.env` local.
4. Valores del perfil.
5. Valores predeterminados del proyecto.

La configuración efectiva debe poder inspeccionarse sin mostrar secretos:

```bash
llm-lab config show --effective
```

## 23. Estrategia de pruebas

### 23.1 Unitarias

- Parsing y validación de perfiles.
- Precedencia de configuración.
- Máquina de estados.
- Construcción de argumentos por runtime.
- Redacción de secretos.
- Códigos de salida.

### 23.2 Integración sin GPU

- Render de Compose.
- Servicio simulado compatible con OpenAI.
- Conflicto de puerto.
- Locks concurrentes.
- Inicio, salud, stop y switch simulados.

### 23.3 Integración con GPU

- `doctor` con RTX 5060 Ti.
- Arranque real de cada perfil.
- Validación de offload.
- Tool calling desde Pi y OpenCode.
- Cambio Qwen → Gemma → Qwen.
- Confirmación de que nunca quedan ambos modelos cargados.
- Reinicio del daemon o contenedor sin pérdida de caches.

### 23.4 Regresión

Cada actualización de runtime debe ejecutar smoke y una suite de performance reducida antes de mover la revisión estable.

## 24. Requisitos no funcionales

- **Reproducibilidad:** perfiles estables fijan revisión y artefactos.
- **Idempotencia:** repetir `start` o `stop` no corrompe estado.
- **Recuperabilidad:** un fallo de inicio deja el sistema en `IDLE` o en un estado diagnosticable, no bloqueado silenciosamente.
- **Portabilidad:** Linux/NVIDIA es la plataforma inicial; la estructura no debe impedir otros backends.
- **Mantenibilidad:** agregar un perfil del mismo runtime no debe requerir modificar la CLI.
- **Tiempo de respuesta del control:** `status` y `profiles` deben responder en menos de un segundo sin despertar un modelo.
- **Persistencia:** detener contenedores no borra modelos ni caches.
- **Transparencia:** la CLI debe poder mostrar el comando y argumentos efectivos del servidor.

## 25. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| MTP requiere forks o PRs no fusionados | Builds frágiles | Fijar revisiones, mantener adaptadores separados y smoke tests |
| Un perfil cabe en pesos pero no con KV cache | OOM o offload lento | Presupuesto de VRAM por contexto y benchmark en hardware objetivo |
| Tool calling difiere entre modelos | Agentes poco confiables | Matriz de capacidades y suite agentic por perfil |
| Puerto ocupado | Inicio fallido | Preflight, mensaje con proceso y configuración alternativa |
| Driver actualizado sin reinicio | Docker no ve GPU | Detectar mismatch y recomendar reinicio, sin tocar el host |
| Cache crece sin control | Presión de disco | `llm-lab storage report` y limpieza explícita por artefacto |
| Cambio deja VRAM retenida | Segundo modelo no inicia | Health/stop gate y verificación de procesos GPU |
| Cuantización reduce razonamiento | Calidad insuficiente | Evaluar tareas reales, conservar perfiles alternativos |
| Endpoint expuesto accidentalmente | Acceso no autorizado | Loopback forzado por defecto y advertencia al cambiar bind |
| Clientes interpretan distinto reasoning/tools | Errores de protocolo | Configuración específica por cliente y pruebas end-to-end |

## 26. Fases de entrega

### Fase 0: bootstrap del repositorio

- Crear `local-llm-agent-lab`.
- Añadir README, AGENTS.md, licencia, estructura y ADR inicial.
- Definir esquema de perfiles.
- Implementar `doctor`, `profiles`, `status` y ayuda.
- Validar Compose sin descargar modelos.

### Fase 1: servidor único y clientes en host

- Implementar adaptador llama.cpp.
- Endpoint `127.0.0.1:18080`.
- Perfil Gemma 4 12B sin MTP como baseline.
- Health gate y logs.
- Plantillas Pi y OpenCode.
- Smoke real desde ambos clientes.

### Fase 2: selección exclusiva de perfiles

- Implementar `start`, `stop` y `switch`.
- Estado, locks y verificación de VRAM.
- Incorporar Qwen 3.6.
- Validar ciclo Qwen ↔ Gemma.

### Fase 3: MTP y optimización

- Gemma 4 12B QAT + MTP.
- Qwen con MTP/NextN.
- Benchmark de `spec-draft-n-max`, KV y contexto.
- Seleccionar valores predeterminados basados en evidencia.

### Fase 4: laboratorio de benchmarks

- Suites smoke, performance y agent.
- JSON reproducible e informes Markdown.
- Comparación llama.cpp directo contra Ollama.
- Comparación experimental con LiteRT-LM para Gemma.

### Fase 5: catálogo ampliado

- Gemma 4 26B-A4B experimental.
- Nuevos Qwen/Gemma y otros modelos.
- Políticas de canales `stable`, `candidate` y `experimental`.
- Gestión explícita de almacenamiento.

## 27. Criterios de aceptación del MVP

El MVP se considerará completo cuando:

1. `llm-lab doctor` valida Docker y GPU sin modificar el host.
2. El servicio solo escucha en `127.0.0.1:18080` por defecto.
3. Pi y OpenCode instalados en el host pueden completar un chat y un tool call desde cualquier directorio.
4. Gemma 4 12B y Qwen 3.6 pueden activarse mediante perfiles versionados.
5. `switch` nunca deja ambos modelos cargados simultáneamente.
6. Los modelos y caches sobreviven a `stop` y reinicios del contenedor.
7. `status --json` identifica perfil, runtime, salud y endpoint.
8. Un conflicto de puerto o VRAM produce un error accionable.
9. Existe al menos un benchmark reproducible por perfil.
10. Ningún secreto, modelo, cache o build generado queda versionado.

## 28. Decisiones iniciales

### Aceptadas

- Crear un repositorio nuevo en lugar de evolucionar el experimento `qwen`.
- Nombre recomendado: `local-llm-agent-lab`.
- Ejecutar clientes/agentes en el host.
- Ejecutar inferencia en contenedores.
- Usar `127.0.0.1:18080` como endpoint predeterminado.
- Cargar un solo modelo principal a la vez.
- Usar llama-server como runtime inicial.
- Mantener Qwen y Gemma como perfiles seleccionables, no servicios concurrentes.
- Priorizar Gemma 4 12B QAT/MTP para equilibrio entre velocidad, contexto y calidad en 16 GB.
- Tratar Gemma 4 26B-A4B como perfil experimental.

### Pendientes de validar

- Lenguaje de implementación de la CLI: Bash estricto para MVP o una CLI tipada en Go/Python.
- Directorio exacto de datos y estrategia volumen Docker frente a bind explícito.
- Revisiones concretas de llama.cpp para cada perfil MTP.
- Artefactos y checksums definitivos.
- Compatibilidad real de `/v1/responses`.
- Calidad de tool calling con thinking activado.
- Contexto máximo sostenible de Qwen y Gemma sin offload involuntario.
- Conveniencia de mantener un alias de modelo único o IDs por perfil en los clientes.

## 29. Preguntas para la sesión de implementación

1. ¿Se creará el repositorio en GitHub, GitLab o solo local inicialmente?
2. ¿La CLI debe empezar en Bash para iterar rápido o en Go para distribuir un binario único?
3. ¿Los modelos se guardarán bajo XDG en el host o en volúmenes Docker nombrados?
4. ¿Se desea importar o reutilizar la cache actual de Qwen sin copiar 13+ GB?
5. ¿El MVP debe incluir MTP desde el primer perfil funcional o establecer primero un baseline sin MTP?
6. ¿La configuración de Pi y OpenCode debe ser generada solamente o instalada mediante una operación explícita con backup?

## 30. Primer backlog sugerido

1. Crear repositorio y documentación base.
2. Escribir ADR de separación host/agente y contenedor/inferencia.
3. Definir JSON Schema o YAML Schema para perfiles.
4. Implementar `llm-lab doctor` sin escrituras.
5. Implementar render de configuración y Compose.
6. Levantar llama-server baseline en `127.0.0.1:18080`.
7. Añadir Gemma 4 12B baseline y smoke HTTP.
8. Generar configuración de Pi y validar desde un proyecto externo.
9. Generar configuración de OpenCode y validar desde un proyecto externo.
10. Implementar ciclo de vida, locks y estado.
11. Añadir Qwen y probar cambio exclusivo.
12. Incorporar MTP y benchmark reproducible.

## 31. Prompt de handoff para una sesión nueva

```text
Vamos a crear un repositorio nuevo llamado `local-llm-agent-lab` siguiendo el
PRD `PRD_LOCAL_LLM_AGENT_LAB.md` que está en `/home/javy/projects/qwen`.

Lee el PRD completo antes de actuar. Empieza por la Fase 0 y mantén el alcance
del MVP. El agente y OpenCode/Pi deben ejecutarse en el host; la inferencia debe
ejecutarse en Docker. El endpoint predeterminado será
`http://127.0.0.1:18080/v1`. Solo puede estar cargado un modelo principal a la
vez. No descargues modelos grandes ni reutilices caches existentes sin revisar
primero el estado del host y pedir confirmación si la acción tendrá un costo
material de disco o tiempo.

Antes de crear archivos, confirma el destino del repositorio, inspecciona las
reglas globales aplicables y propone el plan concreto de Fase 0. Mantén perfiles
de modelo declarativos y evita acoplar la CLI a Qwen, Gemma o llama.cpp.
```


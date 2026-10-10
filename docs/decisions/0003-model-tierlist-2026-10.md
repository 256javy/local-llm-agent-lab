# ADR 0003: tierlist de modelos y perfiles retirados (2026-10)

- Estado: aceptada
- Fecha: 2026-10-10

## Contexto

Las suites locales (`quality`, `tools`, `context`, `performance`) ya no
distinguen entre perfiles: todos las aprueban. La matriz de I-16 sumó
`pi-agent-bench` (21 tareas de eficiencia, seguridad e inyección, variante
`baseline` sin reglas, 2 repeticiones) con llama.cpp `57291f2`, CUDA 13.0.3 y
una RTX 5060 Ti 16 GB. Los modelos se cargan desde el HDD.

| Perfil | Suites | Pi aprobadas | Con daño | Errores tool | tg t/s |
| --- | --- | --- | --- | --- | --- |
| Qwen 3.8 27B IQ3_XXS + MTP | 4/4 | 38/42 | 2 | 4 | 56 |
| Qwen 3.6 35B-A3B Q2 + MTP | 4/4 | 33/42 | 4 | 8 | 143 |
| Saluki 27B IQ2-mix | 4/4 | 33/42 | 4 | 33 | 35 |
| Gemma 4 26B-A4B Q3_K_M | 4/4 | 32/42 | 8 | 158 | 87 |
| Gemma 4 12B QAT + MTP | 4/4 | 30/42 | 10 | 42 | 120 |
| Gemma 4 26B-A4B QAT Q4 + MTP | 3/4 | 28/42 | 4 | 152 | 183 |

n = 2 por tarea: alcanza para diferencias grandes, no para ordenar perfiles
cercanos.

## Decisión

Tierlist para uso como agente con Pi:

- **S — agente principal:** Qwen 3.8 27B. Pasa a ser el perfil por defecto
  (`LLM_LAB_DEFAULT_PROFILE`), en lugar de Gemma 4 12B.
- **A — rápido:** Qwen 3.6 35B-A3B. Iguala a Saluki en aprobadas con 4× su
  velocidad.
- **C como agente — en investigación:** Gemma 4 12B y Gemma 4 26B-A4B QAT. La
  mayoría de sus errores son llamadas `edit` sin `path` repetidas en bucle
  (132 de 152 en el 26B QAT); puede ser el modelo o el parser de tool calls de
  llama.cpp para Gemma 4. Gemma 12B sigue como base de las campañas de Jev.

Perfiles retirados o descartados:

- **Saluki 27B** (`ConwayResearch/Underdog-Saluki-27B-1.0`, revisión
  `4f60eba09f4b6db63c72915d328d97e1d93edb8c`, `Underdog-Saluki-27B-1.0-IQ2-mix.gguf`,
  sha256 `4a673518…5d9efb`, Apache-2.0). Retirado: sobre la misma base que
  Qwen 3.8 aprueba 33/42 contra 38/42, con 8× sus errores de herramienta y
  1,6× más lento (sin MTP). Su ventaja publicada en BFCL no se reprodujo con
  Pi. Su único beneficio, ~3 GB menos de VRAM, no hace falta en este equipo.
- **Gemma 4 26B-A4B Q3_K_M no QAT** (`unsloth/gemma-4-26B-A4B-it-GGUF`).
  Reemplazado por la variante QAT UD-Q4_K_XL con MTP.
- **Qwen3-Coder 30B-A3B Instruct.** Descartado sin descargar: modelo de 2025,
  ~50 % en SWE-bench Verified según su model card, y su rol rápido lo cubre
  Qwen 3.6 35B-A3B.

## Consecuencias

- Pi y los ejemplos de arranque usan Qwen 3.8 por defecto.
- Reincorporar un perfil retirado exige repetir la misma matriz y superar al
  perfil que ocupa su rol.
- Las cifras viven en `docs/BACKLOG.md` (I-16); los JSON crudos quedan fuera
  de Git en `benchmark-results/` y `.local/jev-reviews/`.

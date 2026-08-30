# Perfiles candidatos para 16 GB

El catálogo activo contiene únicamente perfiles con fuentes GGUF y revisiones
fijadas. Esta lista reúne candidatos; no provoca descargas ni promete
compatibilidad hasta completar build, VRAM, contexto, tool calling y benchmarks.

## Prioridad

1. **Qwen3-Coder 30B-A3B Instruct** — perfil `coding-agent`. Probar GGUF Q3/IQ3
   con 16K y 32K; una Q4 puede dejar poco margen en 16 GB. Fuente oficial:
   <https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct>.
2. **Ministral 3 14B Instruct** — perfil `general-balanced`, multilingüe y con
   margen para contexto. Empezar solo texto aunque la familia soporte visión.
   Fuente oficial:
   <https://huggingface.co/mistralai/Ministral-3-14B-Instruct-2512>.
3. **Ministral 3 8B Instruct** — perfil `fast`, usado como baseline de latencia,
   consumo y calidad. Fuente oficial:
   <https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512>.
4. **Phi-4 14B** — baseline denso de razonamiento y código, con contexto oficial
   de 16K. Fuente oficial: <https://huggingface.co/microsoft/phi-4>.
5. **NVIDIA Nemotron Nano 9B v2** — spike experimental de arquitectura híbrida;
   confirmar primero soporte GGUF/llama.cpp y tool template. Fuente oficial:
   <https://huggingface.co/nvidia/NVIDIA-Nemotron-Nano-9B-v2>.

## Gate de incorporación

Antes de crear un JSON bajo `config/profiles/` se debe seleccionar un GGUF
auditable, fijar revisión y checksum, confirmar licencia y plantilla de chat, y
estimar peso más KV cache dentro de 16 GB. El perfil entra como `experimental`
y solo avanza tras pasar `smoke`, `quality`, `tools`, `context`, `performance` y
una ejecución `soak` sin degradación ni fuga de VRAM.

Gemma 3 12B no es prioridad porque solapa el rol ya cubierto por Gemma 4 12B.
Mistral Small 24B y Qwen Coder Q4 pueden caber con ajustes agresivos, pero dejan
menos margen operativo que los candidatos anteriores.

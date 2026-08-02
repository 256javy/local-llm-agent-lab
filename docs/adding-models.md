# Agregar modelos

1. Copia un perfil existente bajo `config/profiles/`.
2. Asigna un `id` único y estable.
3. Fija el repositorio y revisión del runtime.
4. Declara modelo, drafter opcional, contexto, argumentos y requisitos.
5. Ejecuta `./bin/llm-lab profiles`.
6. Ejecuta las pruebas unitarias.
7. Construye con `./bin/llm-lab pull <perfil>`.
8. Completa smoke, tool calling y benchmark antes de cambiar el estado.

Un perfil nuevo del adaptador `llama-cpp` no debe requerir cambios en Python.
Los checksums y revisiones deben completarse antes de marcar un perfil estable.

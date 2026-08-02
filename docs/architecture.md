# Arquitectura

## Separación principal

Los clientes se ejecutan en el host para acceder directamente al directorio
actual, Git, SDKs y credenciales del usuario. El runtime de inferencia se
ejecuta en Docker y solo publica una API en loopback.

```text
Pi / OpenCode en $PWD
        |
        | OpenAI-compatible HTTP
        v
127.0.0.1:18080
        |
        v
contenedor del perfil activo -> GPU NVIDIA
```

## Estado exclusivo

La CLI mantiene un lock y un archivo de estado local. `switch` detiene el
contenedor administrado, espera su salida y solo después inicia el siguiente.
Nunca termina procesos GPU ajenos.

## Perfiles

Los perfiles JSON contienen fuentes de modelos, runtime, argumentos y
capacidades. El adaptador construye el comando sin lógica específica por modelo
en la CLI.

## Red

Compose publica `${LLM_LAB_HOST}:${LLM_LAB_PORT}:8080`. El valor predeterminado
de `LLM_LAB_HOST` es `127.0.0.1`; una exposición distinta requiere una decisión
explícita del operador.

# ADR 0001: clientes en host e inferencia en contenedor

- Estado: aceptada
- Fecha: 2026-08-02

## Decisión

Pi, OpenCode y futuras herramientas agentic se ejecutan en el host. Los modelos
y runtimes de inferencia se ejecutan en Docker detrás de una API local estable.

## Consecuencias

- No se requieren bind mounts por proyecto.
- Los agentes usan naturalmente las herramientas y credenciales del host.
- El runtime puede cambiar sin reconfigurar el workspace.
- El endpoint y las diferencias de compatibilidad deben administrarse como un
  contrato explícito.

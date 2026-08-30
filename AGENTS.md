# AGENTS.md

## Contexto

Este repositorio administra runtimes locales de LLM en Docker para clientes que
se ejecutan directamente en el host, inicialmente Pi Coding Agent y OpenCode.
El contrato público predeterminado es `http://127.0.0.1:18080/v1`.

La arquitectura y las decisiones aceptadas se encuentran en `docs/architecture.md`
y `docs/decisions/`. El estado vivo de implementación se mantiene en
`docs/BACKLOG.md`.

## Reglas

- No commitear `.env`, tokens, modelos, caches, builds ni resultados locales.
- No exponer el servidor fuera de loopback por defecto.
- No iniciar dos perfiles consumidores de GPU simultáneamente.
- No terminar procesos GPU que no pertenezcan al proyecto.
- Mantener perfiles declarativos; agregar un modelo no debe requerir editar la CLI.
- Fijar revisiones de runtimes y modelos cuando un perfil pase a estable.
- Mantener mensajes, documentación humana y CLI en español; código e identificadores en inglés.
- Después de crear commits, hacer push si existe un remoto configurado.
- Los merges son manuales salvo solicitud explícita.

## Validación

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
./bin/llm-lab profiles
./bin/llm-lab config show --effective
./bin/llm-lab doctor
docker compose config --quiet
```

Las validaciones que descargan modelos o construyen runtimes pesados deben
ejecutarse explícitamente y registrarse en `docs/BACKLOG.md`.

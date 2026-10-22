# Papercuts

Problemas que frenaron el desarrollo en este repo y cómo se resolvieron. Agrega al final una línea `- YYYY-MM-DD · host · síntoma · fix`; si necesita detalle, líneas siguientes indentadas con dos espacios. Busca aquí con `grep -i` ante una falla rara de build, tests o CI.

- 2026-10-11 · local · `unittest` falla con `assertEqual(x, 5)` reportando `5 != 4`: `.pyc` obsoleto, porque el `.py` se editó en el mismo segundo y con el mismo tamaño (Python invalida por mtime en segundos + tamaño) · `touch` al `.py` o `PYTHONDONTWRITEBYTECODE=1`
- 2026-10-18 · local · un perfil gemma 31B IQ3_XXS con MTP abortaba en `pi-agent-bench` con `CUDA error: the launch timed out` (watchdog de la GPU compartida con el display, prompt de ~18K) · pendiente: probar con la GPU sin escritorio (X apagado) o con `--ubatch-size`/contexto menores; el perfil ya no está en `config/profiles/`

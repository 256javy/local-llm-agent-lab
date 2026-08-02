# ADR 0002: un único perfil activo

- Estado: aceptada
- Fecha: 2026-08-02

## Decisión

El plano de control permite un único perfil consumidor de GPU activo. Cambiar
de perfil implica detener el actual y verificar su salida antes de iniciar otro.

## Consecuencias

- Se evita competir por los 16 GB de VRAM.
- El puerto público permanece estable.
- El cambio tiene latencia de descarga/carga y debe ser visible al operador.

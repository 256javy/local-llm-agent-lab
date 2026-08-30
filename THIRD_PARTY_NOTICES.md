# Créditos y licencias de terceros

Local LLM Agent Lab es un proyecto independiente distribuido bajo licencia MIT.
La licencia del repositorio no reemplaza las licencias de runtimes, imágenes,
bibliotecas ni modelos que cada usuario decida descargar.

## Runtime y plataforma

- [llama.cpp](https://github.com/ggml-org/llama.cpp), proyecto de Georgi
  Gerganov y contribuidores — MIT.
- [NVIDIA CUDA Container Images](https://catalog.ngc.nvidia.com/orgs/nvidia/containers/cuda)
  — sujetos a los términos aplicables de NVIDIA CUDA y NGC.
- Docker y Docker Compose — sujetos a sus respectivas licencias y términos.

## TUI Rust

Dependencias directas declaradas en `tui-v2/Cargo.toml`:

- ratatui y crossterm — MIT.
- color-eyre, serde, serde_json, chrono, fd-lock y unicode-width — MIT o
  Apache-2.0.
- nix — MIT.

`tui-v2/Cargo.lock` conserva las versiones exactas y el árbol transitivo. Las
notificaciones completas de una distribución binaria deben generarse a partir
de ese lockfile, incluyendo dependencias transitivas.

## Modelos y datos

Los perfiles solo describen dónde obtener modelos. Los archivos GGUF no se
redistribuyen con este repositorio. Cada modelo mantiene la licencia indicada
por su publicador en Hugging Face; algunas familias, como Gemma, exigen aceptar
términos específicos. Las cuantizaciones de terceros pueden añadir condiciones
o atribuciones propias y deben revisarse antes de redistribuirlas.

Los benchmarks externos —por ejemplo lm-evaluation-harness, BFCL o SWE-bench—
también conservan sus licencias y las de sus datasets. Este repositorio no los
incluye ni descarga automáticamente.

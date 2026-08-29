#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
release_bin="${script_dir}/target/release/tui-v2"
debug_bin="${script_dir}/target/debug/tui-v2"

if [[ -x "${release_bin}" ]]; then
    exec "${release_bin}" "$@"
fi

if [[ -x "${debug_bin}" ]]; then
    exec "${debug_bin}" "$@"
fi

echo "Compilando tui-v2 (primera ejecución)…" >&2
if ! (cd "${script_dir}" && cargo build --release); then
    echo "ERROR: no se pudo compilar tui-v2" >&2
    exit 1
fi

exec "${release_bin}" "$@"
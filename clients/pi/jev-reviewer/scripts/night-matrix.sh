#!/usr/bin/env bash
# Matriz nocturna de pi-agent-bench: un perfil por vez, apaga el servidor al terminar.
# Uso: scripts/night-matrix.sh [perfil ...]  (por defecto Qwen 3.8 27B y Gemma 4 26B)
# Variables: VARIANTS (baseline,local), REPETITIONS (2), THINKING (off), TIMEOUT (600), TASKS (todas).
set -uo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
lab=$(cd "$here/../../.." && pwd)
[ $# -gt 0 ] || set -- qwen-3.8-27b-iq3xxs-mtp gemma-4-26b-a4b-qat-mtp
log="$lab/.local/night-matrix-$(date +%Y%m%d-%H%M).log"
mkdir -p "$lab/.local"
trap '"$lab/bin/llm-lab" stop >>"$log" 2>&1' EXIT
for p in "$@"; do
  echo "== $(date -Is) $p" | tee -a "$log"
  "$lab/bin/llm-lab" switch "$p" >>"$log" 2>&1 || { echo "falló switch a $p" | tee -a "$log"; continue; }
  for _ in $(seq 60); do "$lab/bin/llm-lab" health >/dev/null 2>&1 && break; sleep 10; done
  (cd "$here" && npm run bench -- --provider local-lab --model "$p" --profile "$p" \
    --variants "${VARIANTS:-baseline,local}" --repetitions "${REPETITIONS:-2}" \
    --thinking "${THINKING:-off}" --timeout "${TIMEOUT:-600}" \
    ${TASKS:+--tasks "$TASKS"}) >>"$log" 2>&1
  echo "== $(date -Is) $p terminó ($?)" | tee -a "$log"
done

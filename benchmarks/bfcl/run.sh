#!/usr/bin/env bash
# BFCL (Berkeley Function Calling Leaderboard) contra el endpoint local: un perfil por vez.
# Uso: benchmarks/bfcl/run.sh perfil [perfil ...]
# Variables: CATEGORIES (ver abajo), SAMPLE (50 casos por categoría), BFCL_HOME (venv y
#   resultados en el HDD), THREADS (1).
# Venv: python3 -m venv $BFCL_HOME/venv; pip install --no-cache-dir torch --index-url
#   https://download.pytorch.org/whl/cpu; pip install --no-cache-dir bfcl-eval soundfile
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
lab=$(cd "$here/../.." && pwd)
BFCL_HOME=${BFCL_HOME:-/mnt/storage-lv/local-llm-agent-lab/bfcl}
CATEGORIES=${CATEGORIES:-simple_python,multiple,parallel,parallel_multiple,irrelevance,live_simple,live_multiple,live_irrelevance,multi_turn_base}
[ $# -gt 0 ] || { echo "uso: $0 perfil [perfil ...]" >&2; exit 2; }
export BFCL_PROJECT_ROOT="$BFCL_HOME/project" BFCL_LOCAL_MODELS=$(IFS=,; echo "$*")
mkdir -p "$BFCL_PROJECT_ROOT" "$lab/.local"
log="$lab/.local/bfcl-$(date +%Y%m%d-%H%M).log"
bfcl() { "$BFCL_HOME/venv/bin/python" "$here/bfcl_local.py" "$@"; }
trap '"$lab/bin/llm-lab" stop >>"$log" 2>&1; echo "== FIN" >>"$log"' EXIT
# Muestra fija por categoría (SAMPLE casos, semilla 0) para que todos los perfiles vean los mismos.
"$BFCL_HOME/venv/bin/python" - "$CATEGORIES" "${SAMPLE:-50}" >"$BFCL_PROJECT_ROOT/test_case_ids_to_generate.json" <<'EOF'
import json, random, sys
from importlib.resources import files
data = files("bfcl_eval") / "data"
out = {}
for cat in sys.argv[1].split(","):
    ids = [json.loads(l)["id"] for l in (data / f"BFCL_v4_{cat}.json").read_text().splitlines() if l.strip()]
    out[cat] = sorted(random.Random(0).sample(ids, min(int(sys.argv[2]), len(ids))))
print(json.dumps(out))
EOF
for p in "$@"; do
  echo "== $(date -Is) $p" | tee -a "$log"
  # Si el servidor se cae a mitad de camino (p. ej. watchdog de CUDA), lo reinicia y
  # regenera solo los casos que quedaron con error de conexión.
  for round in $(seq "${ROUNDS:-5}"); do
    "$lab/bin/llm-lab" switch "$p" >>"$log" 2>&1 || { echo "falló switch a $p" | tee -a "$log"; break; }
    for _ in $(seq 60); do "$lab/bin/llm-lab" health >/dev/null 2>&1 && break; sleep 10; done
    bfcl generate --model "$p" --run-ids --num-threads "${THREADS:-1}" >>"$log" 2>&1
    left=$("$BFCL_HOME/venv/bin/python" - "$BFCL_PROJECT_ROOT/result/$p" <<'EOF'
import json, pathlib, sys
left = 0
for f in pathlib.Path(sys.argv[1]).rglob("*_result.json"):
    rows = [l for l in f.read_text().splitlines() if l.strip()]
    keep = [l for l in rows if "Error during inference: Connection error" not in l]
    left += len(rows) - len(keep)
    f.write_text("".join(l + "\n" for l in keep))
print(left)
EOF
)
    echo "== $(date -Is) $p ronda $round: $left casos con error de conexión" | tee -a "$log"
    [ "$left" -eq 0 ] && break
  done
  bfcl evaluate --model "$p" --test-category "$CATEGORIES" --partial-eval >>"$log" 2>&1
  echo "== $(date -Is) $p terminó ($?)" | tee -a "$log"
done
bfcl scores >>"$log" 2>&1

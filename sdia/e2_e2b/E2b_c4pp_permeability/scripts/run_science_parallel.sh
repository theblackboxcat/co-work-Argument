#!/bin/bash
# E2b science: 8 Dx2 clean seeds. Config from tune/selected_config.json (or --config).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SEEDS=(200 205 210 211 212 216 218 219)
if [[ -n "${1:-}" ]]; then
  CFG="$1"
elif [[ -f tune/selected_config.json ]]; then
  CFG=$(python3 -c "import json; print(json.load(open('tune/selected_config.json'))['selected_config_id'])")
else
  CFG=ceil_lr1e3
fi
mkdir -p logs
echo "[E2b science] start $(date '+%F %T %z') cfg=$CFG thr=$(cut -d' ' -f1 frozen/thresholds_E2b.sha256)"
echo "$CFG" > logs/science_config_id.txt
PIDS=()
for s in "${SEEDS[@]}"; do
  if [[ -f "logs/result_seed${s}.json" ]]; then
    echo "[E2b] seed $s already done, skip"
    continue
  fi
  python3 run_arm.py --seed "$s" --config "$CFG" > "logs/run_seed${s}.log" 2>&1 &
  PIDS+=($!)
  echo "[E2b] launched seed $s cfg=$CFG pid=${PIDS[-1]}"
done
ec=0
for pid in "${PIDS[@]:-}"; do
  if ! wait "$pid"; then echo "[E2b] pid $pid FAILED"; ec=1; fi
done
echo "[E2b] all workers done ec=$ec $(date '+%F %T %z')"
python3 scripts/summarize_e2b.py
exit $ec

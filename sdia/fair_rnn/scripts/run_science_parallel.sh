#!/bin/bash
# Fair-RNN science: Dx2 clean 8 seeds with selected config. VOID denom=8. S3 CLOSED.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SEEDS=(200 205 210 211 212 216 218 219)
if [[ -n "${1:-}" ]]; then
  CFG="$1"
elif [[ -f tune/selected_config.json ]]; then
  CFG=$(python3 -c "import json; print(json.load(open('tune/selected_config.json'))['selected_config_id'])")
else
  echo "ERROR: no config; run scripts/run_tune.sh first or pass config id" >&2
  exit 2
fi
mkdir -p logs
THR=$(cut -d' ' -f1 frozen/thresholds_fair_RNN.sha256)
echo "[fair_RNN science] start $(date '+%F %T %z') cfg=$CFG thr=$THR"
echo "[fair_RNN science] S3=CLOSED; never claim 门控普遍必要; E2b untouched"
echo "$CFG" > logs/science_config_id.txt
PIDS=()
for s in "${SEEDS[@]}"; do
  out="logs/result_arm_G_RL_RNN_fair_seed${s}_${CFG}.json"
  if [[ -f "$out" ]]; then
    echo "[fair_RNN science] $out exists, skip"
    continue
  fi
  python3 run_arm.py --arm G_RL_RNN_fair --seed "$s" --config "$CFG" \
    > "logs/run_seed${s}_${CFG}.log" 2>&1 &
  PIDS+=($!)
  echo "[fair_RNN science] launched seed=$s cfg=$CFG pid=${PIDS[-1]}"
done
ec=0
for pid in "${PIDS[@]:-}"; do
  if ! wait "$pid"; then echo "[fair_RNN science] pid $pid FAILED"; ec=1; fi
done
echo "[fair_RNN science] all workers done ec=$ec $(date '+%F %T %z')"
python3 scripts/summarize_fair_rnn.py
exit $ec

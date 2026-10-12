#!/bin/bash
# Limited tune: configs × seeds 100,101 (within 100-103). Thresholds already frozen.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
CONFIGS=(ceil_lr1e3 ceil_lr5e4)
SEEDS=(100 101)
mkdir -p tune
echo "[E2b tune] start $(date '+%F %T %z') thr=$(cut -d' ' -f1 frozen/thresholds_E2b.sha256)"
PIDS=()
for cfg in "${CONFIGS[@]}"; do
  for s in "${SEEDS[@]}"; do
    out="tune/result_seed${s}_${cfg}.json"
    if [[ -f "$out" ]]; then
      echo "[E2b tune] $out exists, skip"
      continue
    fi
    python3 run_arm.py --seed "$s" --config "$cfg" --tune > "tune/run_seed${s}_${cfg}.log" 2>&1 &
    PIDS+=($!)
    echo "[E2b tune] launched seed=$s cfg=$cfg pid=${PIDS[-1]}"
  done
done
ec=0
for pid in "${PIDS[@]:-}"; do
  if ! wait "$pid"; then echo "[E2b tune] pid $pid FAILED"; ec=1; fi
done
echo "[E2b tune] done ec=$ec $(date '+%F %T %z')"
python3 scripts/select_tune.py
exit $ec

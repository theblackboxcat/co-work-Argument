#!/bin/bash
# E2 science: 8 Dx2 clean seeds in parallel. Thresholds already frozen.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SEEDS=(200 205 210 211 212 216 218 219)
mkdir -p logs
echo "[E2] starting science $(date '+%F %T %z') thr=$(cut -d' ' -f1 frozen/thresholds_E2.sha256)"
PIDS=()
for s in "${SEEDS[@]}"; do
  if [[ -f "logs/result_seed${s}.json" ]]; then
    echo "[E2] seed $s already done, skip"
    continue
  fi
  python3 run_arm.py --arm ALL --seed "$s" > "logs/run_seed${s}.log" 2>&1 &
  PIDS+=($!)
  echo "[E2] launched seed $s pid ${PIDS[-1]}"
done
ec=0
for pid in "${PIDS[@]:-}"; do
  if ! wait "$pid"; then
    echo "[E2] pid $pid FAILED"
    ec=1
  fi
done
echo "[E2] all workers done ec=$ec $(date '+%F %T %z')"
exit $ec

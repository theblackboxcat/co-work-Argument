#!/bin/bash
# Fair-RNN tune: all tune_grid configs × seeds 100-103. NEVER science seeds.
# Optional: FAIR_RNN_MAX_PARALLEL=4 (default 4). Use SKIP_FULL_EVAL=1 for overnight speed (proxy).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SEEDS=(100 101 102 103)
CONFIGS=(baseline_s1g orth_h32_lr1e3 orth_h32_lr3e4_clip1 identity_h32_lr1e3 orth_h64_lr5e4 orth_h48_lr1e3_ep1200)
MAXP="${FAIR_RNN_MAX_PARALLEL:-4}"
SKIP_FLAG=()
if [[ "${SKIP_FULL_EVAL:-1}" == "1" ]]; then
  SKIP_FLAG=(--skip_full_eval)
fi
mkdir -p tune
THR=$(cut -d' ' -f1 frozen/thresholds_fair_RNN.sha256)
echo "[fair_RNN tune] start $(date '+%F %T %z') thr=$THR max_parallel=$MAXP skip_full_eval=${SKIP_FULL_EVAL:-1}"
echo "[fair_RNN tune] S3=CLOSED E2b=do_not_reopen"
running=0
ec=0
PIDS=()
launch() {
  local s="$1" cfg="$2"
  local out="tune/result_arm_G_RL_RNN_fair_seed${s}_${cfg}.json"
  if [[ -f "$out" ]]; then
    echo "[fair_RNN tune] $out exists, skip"
    return 0
  fi
  python3 run_arm.py --arm G_RL_RNN_fair --seed "$s" --config "$cfg" --tune "${SKIP_FLAG[@]}" \
    > "tune/run_seed${s}_${cfg}.log" 2>&1 &
  PIDS+=($!)
  echo "[fair_RNN tune] launched seed=$s cfg=$cfg pid=${PIDS[-1]}"
  running=$((running+1))
}
wait_one() {
  if ((${#PIDS[@]}==0)); then return 0; fi
  local pid="${PIDS[0]}"
  PIDS=("${PIDS[@]:1}")
  if ! wait "$pid"; then echo "[fair_RNN tune] pid $pid FAILED"; ec=1; fi
  running=$((running-1))
}
for cfg in "${CONFIGS[@]}"; do
  for s in "${SEEDS[@]}"; do
    while (( running >= MAXP )); do wait_one; done
    launch "$s" "$cfg" || true
  done
done
while ((${#PIDS[@]})); do wait_one; done
echo "[fair_RNN tune] done ec=$ec $(date '+%F %T %z')"
python3 scripts/select_tune.py
exit $ec

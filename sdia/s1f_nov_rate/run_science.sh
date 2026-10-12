#!/bin/bash
set -euo pipefail
ROOT="/workspace/proj_20261009/必要性重建/S1f_nov_rate"
cd "$ROOT"
MAX=4
run_one() {
  local seed=$1 rep=$2
  local out="logs/result_arm_Nov_seed${seed}_r${rep}.json"
  if [[ -f "$out" ]]; then
    echo "[skip] exists $out"
    return 0
  fi
  echo "[start] seed=$seed r=$rep $(date '+%H:%M:%S')"
  python3 run_arm.py --arm Nov --seed "$seed" --replica "$rep" \
    > "logs/run_seed${seed}_r${rep}.stdout" 2>&1
  echo "[done] seed=$seed r=$rep $(date '+%H:%M:%S')"
}
export -f run_one
# GNU parallel if available, else xargs
if command -v parallel >/dev/null 2>&1; then
  parallel -j "$MAX" --colsep ':' run_one {1} {2} :::: logs/science_joblist.txt
else
  # bash job control pool
  active=0
  while IFS=: read -r seed rep; do
    while [[ $(jobs -rp | wc -l) -ge $MAX ]]; do sleep 2; done
    run_one "$seed" "$rep" &
  done < logs/science_joblist.txt
  wait
fi
echo "ALL_SCIENCE_DONE $(date '+%Y-%m-%dT%H:%M:%S%z')"

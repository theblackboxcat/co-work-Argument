#!/bin/bash
# Optional ≤2 min smoke on THIS box or sub-machine. Does NOT count as science.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
echo "[smoke] start $(date '+%F %T %z')"
python3 run_arm.py --arm G_RL_RNN_fair --seed 100 --config baseline_s1g --tune --smoke --skip_full_eval
echo "[smoke] OK — not science; thresholds unchanged"

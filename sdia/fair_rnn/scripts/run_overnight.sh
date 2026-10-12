#!/bin/bash
# Primary overnight job: tune → select → science → summarize. STOP after report.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
echo "===== fair_RNN overnight PRIMARY $(date '+%F %T %z') ====="
echo "LOCKED: S3 CLOSED | E2b untouched | tune seeds 100-103 only | VOID denom=8"
bash scripts/run_tune.sh
bash scripts/run_science_parallel.sh
python3 scripts/summarize_fair_rnn.py
echo "===== DONE: write 报告.md using templates/报告_模板.md then STOP ====="
echo "FORBIDDEN: open S3 | reopen E2b | claim 门控普遍必要 | tune on science seeds"

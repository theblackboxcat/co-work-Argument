#!/usr/bin/env bash
# E05b Arm-C 升级 · 18 calls · key 只来自环境变量 DOTS3_API_KEY
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"; cd "$ROOT"
TS="${TS:-$(date +%Y%m%d_%H%M%S)}"; mkdir -p out

# 断言：包内无硬编码 key
python3 - <<'PY'
import json, re, sys
from pathlib import Path
ex = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
if (ex.get("api_key") or "").strip():
    sys.exit("FATAL: config.example.json has a hardcoded api_key")
for p in list(Path("scripts").rglob("*.py")) + [Path("run_armc.sh")]:
    t = p.read_text(encoding="utf-8", errors="ignore")
    if re.search(r"sk-[A-Za-z0-9]{16,}", t) or re.search(r"Bearer [A-Za-z0-9._\-]{16,}", t):
        sys.exit("FATAL: key-like string in %s" % p)
print("no_hardcoded_key_ok")
PY

# key 只从环境变量 DOTS3_API_KEY 读（公开仓库版）：不写 config.json；
# config.example.json 的 api_key 留空，lib/providers.py 对 provider=dots3 自动取 DOTS3_API_KEY。
if [[ "${ARMC_MOCK:-0}" != "1" ]]; then
  [[ -n "${DOTS3_API_KEY:-}" ]] || { echo "ERROR: export DOTS3_API_KEY=...（本仓库不含 key，也不使用 config.json）"; exit 2; }
fi
CFG=config.example.json

ANCH=PRIVATE_anchors/anchors_e05b_seq_retest.json   # 私人锚，公开仓库不含
[[ -f "$ANCH" ]] || { echo "ERROR: 私人锚不在公开仓库内（$ANCH）。"; exit 3; }
python3 scripts/run_armc.py --config "$CFG" --trunk trunk/trunk_v2_covered_gloss_s14_s27.json \
  --anchors "$ANCH" --repeat 3 --timeout "${TIMEOUT:-90}" --out "out/armc_raw_${TS}.jsonl"
python3 scripts/score_armc.py --raw "out/armc_raw_${TS}.jsonl" --anchors "$ANCH" \
  --out-scores "out/armc_scores_${TS}.json" --out-summary "out/armc_summary_${TS}.md"
echo "回传：out/armc_raw_${TS}.jsonl  out/armc_scores_${TS}.json  out/armc_summary_${TS}.md"
echo "zip -j E05b_ArmC_results_${TS}.zip out/armc_raw_${TS}.jsonl out/armc_scores_${TS}.json out/armc_summary_${TS}.md"

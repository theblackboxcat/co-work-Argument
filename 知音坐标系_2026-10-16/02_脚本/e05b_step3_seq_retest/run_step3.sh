#!/usr/bin/env bash
# E05b Step3 · mutual-recognition retest (auth B trunk · covered ×3 · DRAFT scoring)
# Requires: python3, dots3 reachable, DOTS3_API_KEY (env only)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

TS="${TS:-$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="$ROOT/out"
mkdir -p "$OUT_DIR" "$ROOT/scripts/runs"

# --- key：只从环境变量 DOTS3_API_KEY 读（公开仓库版）---
# 不写 config.json、不把 key 落盘。config.example.json 的 api_key 留空，
# lib/providers.py 的 resolve() 对 provider=dots3 会自动取 DOTS3_API_KEY。
if [[ -z "${DOTS3_API_KEY:-}" ]]; then
  echo "ERROR: 请先 export DOTS3_API_KEY=...（本仓库不含 key，也不使用 config.json）"
  exit 2
fi
python3 - <<'PY'
import json, sys
c = json.load(open("config.example.json", encoding="utf-8"))
if (c.get("api_key") or "").strip():
    sys.exit("FATAL: config.example.json 不应含 api_key")
print("config_ok provider=%s model=%s (key from DOTS3_API_KEY)" % (c.get("provider"), c.get("model")))
PY

TRUNK="$ROOT/trunk/trunk_v2_covered_gloss_s14_s27.json"
ANCHORS="$ROOT/PRIVATE_anchors/anchors_e05b_seq_retest.json"   # 私人锚，公开仓库不含；见 PRIVATE_anchors/README_不入库.md
[[ -f "$ANCHORS" ]] || { echo "ERROR: 私人锚不在公开仓库内（$ANCHORS）。本脚本仅供审阅/有授权语料者复现。"; exit 3; }
CFG="$ROOT/config.example.json"

echo "=== E05b Step3 probe+run ts=$TS ==="
echo "trunk=$TRUNK"
echo "anchors=$ANCHORS"
echo "NOTE: using AUTH B trunk only. OPTIONAL DRAFT trunk is NOT loaded."
echo "NOTE: do NOT freeze Arm-B; do NOT claim 知音 proven; do NOT close E7."

set +e
python3 "$ROOT/scripts/run_v2.py" \
  --config "$CFG" \
  --trunk "$TRUNK" \
  --anchors "$ANCHORS" \
  --arms covered \
  --repeat 3 \
  --timeout "${TIMEOUT:-90}"
RUN_RC=$?
set -e

# find newest jsonl written by run_v2
JSONL=$(ls -1t "$ROOT/scripts/runs"/v2_*.jsonl 2>/dev/null | head -1 || true)
FINAL_JSONL="$OUT_DIR/e05b_seq_retest_${TS}.jsonl"

if [[ -n "${JSONL:-}" && -f "$JSONL" ]]; then
  cp "$JSONL" "$FINAL_JSONL"
  echo "copied $JSONL -> $FINAL_JSONL"
  API_FLAG=auto
  if [[ "$RUN_RC" -ne 0 ]]; then
    API_FLAG=false
  fi
else
  echo "WARNING: no jsonl produced (probe/API fail?). Writing INC decision without inventing numbers."
  FINAL_JSONL="$OUT_DIR/e05b_seq_retest_${TS}.MISSING.jsonl"
  echo '{"type":"meta","ts":"'"$TS"'","error":"no_jsonl","api_failed":true}' > "$FINAL_JSONL"
  API_FLAG=false
  RUN_RC=2
fi

python3 "$ROOT/scripts/score_step3.py" \
  --jsonl "$FINAL_JSONL" \
  --out-dir "$OUT_DIR" \
  --ts "$TS" \
  --host-note "run_step3.sh on $(hostname 2>/dev/null || echo unknown)" \
  --api-ok "$API_FLAG"

echo ""
echo "=== DONE rc=$RUN_RC ==="
echo "回传给作者/Ollie 的三件套："
echo "  1) $FINAL_JSONL"
echo "  2) $OUT_DIR/summary_E05b_Step3_${TS}.md"
echo "  3) $OUT_DIR/decision_E05b_Step3_${TS}.json"
echo "可用:  zip -j E05b_Step3_results_${TS}.zip $FINAL_JSONL $OUT_DIR/summary_E05b_Step3_${TS}.md $OUT_DIR/decision_E05b_Step3_${TS}.json"
exit "$RUN_RC"

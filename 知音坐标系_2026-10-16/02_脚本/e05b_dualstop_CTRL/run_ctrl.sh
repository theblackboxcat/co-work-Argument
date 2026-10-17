#!/usr/bin/env bash
# E05b dual-stop CTRL · auth B · NO dual-bias pressure · covered ×3
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

# Hard assert: COVERED_SYSTEM must NOT contain dual-bias
python3 - <<'PY'
from pathlib import Path
t = Path("scripts/run_v2.py").read_text(encoding="utf-8")
if "dual-stop 同址摄取加压" in t or "默认偏置双停" in t:
    raise SystemExit("FATAL: dual-bias paragraph still in COVERED_SYSTEM — this is CTRL pack")
print("prompt_ok: NO dual-bias in COVERED_SYSTEM")
PY

TRUNK="$ROOT/trunk/trunk_v2_covered_gloss_s14_s27.json"
ANCHORS="$ROOT/PRIVATE_anchors/anchors_e05b_seq_retest.json"   # 私人锚，公开仓库不含；见 PRIVATE_anchors/README_不入库.md
[[ -f "$ANCHORS" ]] || { echo "ERROR: 私人锚不在公开仓库内（$ANCHORS）。本脚本仅供审阅/有授权语料者复现。"; exit 3; }

echo "=== E05b dual-stop CTRL (unpressured) ts=$TS ==="
echo "trunk=AUTH B · prompt=Step3-style (no dual-bias) · ~9 calls"
echo "ref pressurized=20261017_144249 dual 3/3"

set +e
python3 "$ROOT/scripts/run_v2.py" \
  --config "$ROOT/config.example.json" \
  --trunk "$TRUNK" \
  --anchors "$ANCHORS" \
  --arms covered \
  --repeat 3 \
  --timeout "${TIMEOUT:-90}"
RUN_RC=$?
set -e

JSONL=$(ls -1t "$ROOT/scripts/runs"/v2_*.jsonl 2>/dev/null | head -1 || true)
FINAL_JSONL="$OUT_DIR/e05b_dualstop_CTRL_${TS}.jsonl"

if [[ -n "${JSONL:-}" && -f "$JSONL" ]]; then
  cp "$JSONL" "$FINAL_JSONL"
  API_FLAG=auto
  [[ "$RUN_RC" -ne 0 ]] && API_FLAG=false
else
  echo "WARNING: no jsonl"
  FINAL_JSONL="$OUT_DIR/e05b_dualstop_CTRL_${TS}.MISSING.jsonl"
  echo '{"type":"meta","ts":"'"$TS"'","error":"no_jsonl","api_failed":true}' > "$FINAL_JSONL"
  API_FLAG=false
  RUN_RC=2
fi

python3 "$ROOT/scripts/score_ctrl.py" \
  --jsonl "$FINAL_JSONL" \
  --out-dir "$OUT_DIR" \
  --ts "$TS" \
  --host-note "run_ctrl.sh on $(hostname 2>/dev/null || echo unknown)" \
  --api-ok "$API_FLAG"

echo ""
echo "=== DONE rc=$RUN_RC ==="
echo "回传三件套："
echo "  1) $FINAL_JSONL"
echo "  2) $OUT_DIR/summary_E05b_dualstop_CTRL_${TS}.md"
echo "  3) $OUT_DIR/decision_E05b_dualstop_CTRL_${TS}.json"
echo "zip -j E05b_dualstop_CTRL_results_${TS}.zip $FINAL_JSONL $OUT_DIR/summary_E05b_dualstop_CTRL_${TS}.md $OUT_DIR/decision_E05b_dualstop_CTRL_${TS}.json"
exit "$RUN_RC"

#!/usr/bin/env bash
# 全集复现脚本（在 07_本轮实验资产_2026-10-16/ 目录下执行）
#
# 用法：
#   cd 知音坐标系_工程资料_去重版_2026-10-16/07_本轮实验资产_2026-10-16
#   bash 复现.sh
#
# 说明：E0 是零算力（不发任何请求）。其余实验会向端点发请求，
#       需先准备 config.json（见同目录 config.example.json），会消耗额度。

set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"          # 工程根目录（去重版；2026-10-16 起单包结构）

echo "== E0 零算力核验：修正计分器重算五次试跑 =="
# score_v5_corrected.py 期望 --v4pkg 下有一个 pkg/ 子目录装着 v4 的两件；
# 全集中 v4 散落在 04_原始数据_runs 与 06_新包核验与续证，这里临时拼出该布局。
SHIM="$(mktemp -d)"
mkdir -p "$SHIM/pkg"
cp "$ROOT/04_原始数据_runs/v4_s14narrowed_20261015_173608.jsonl" "$SHIM/pkg/"
cp "$ROOT/06_新包核验与续证/实验补报_2026-10-15/trunk_v4_s14_narrowed_DRAFT.json" \
   "$SHIM/pkg/trunk_v4_s14_narrowed_DRAFT.json"

python3 "$HERE/02_实验/E0_零算力核验/score_v5_corrected.py" \
        --pkg "$ROOT" --v4pkg "$SHIM" > /tmp/E0_rerun.txt

if diff -q /tmp/E0_rerun.txt "$HERE/02_实验/E0_零算力核验/score_v5_output.txt" >/dev/null; then
  echo "   ✓ 复跑输出与归档逐字节一致"
else
  echo "   ** 复跑输出与归档不一致，请检查 **"
fi
rm -rf "$SHIM"

echo
echo "== 需要端点（会发请求）的实验 =="
echo "   先：cp $HERE/config.example.json $HERE/config.json  # 填入 api_key"
echo "   E1 形式对照： python3 $HERE/02_实验/E1_形式对照_定位vs判断/exp_discriminate.py"
echo "   E1 形式对照： python3 $HERE/02_实验/E1_形式对照_定位vs判断/exp_format_contrast.py"
echo "   E2 协变测量： python3 $HERE/02_实验/E2_协变测量/exp_covary.py"
echo "   E4 规模对话： python3 $HERE/02_实验/E4_规模对话_长度与意义度/scale_dialogue.py --cond C1 --maxturns 24"
echo "   E5/E6 对话：  python3 $HERE/02_实验/E5_现场对话_闸门修正/live_dialogue.py --gate --mine \"…\" --pos \"…\""
echo "   E7 无引导批量：python3 $HERE/02_实验/E7_费曼线_无引导批量/feynman_batch.py"
echo
echo "== 原始双臂实验重跑（需端点）=="
echo "   python3 $ROOT/02_脚本/run_v3_s14s20sharpen.py   # 用法见该文件头部"
echo
echo "== 注意 =="
echo "   私钥只放 config.json（与脚本同目录），不要提交到公开库。"

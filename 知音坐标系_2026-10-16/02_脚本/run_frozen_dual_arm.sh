#!/usr/bin/env bash
# Frozen dual-arm runner — requires local config.json with reachable dots3.
set -euo pipefail
cd "$(dirname "$0")"
test -f config.json || { echo "missing config.json (copy from config.example.json and fill key)"; exit 1; }
python3 run_v2.py \
  --config config.json \
  --trunk ../03_锚与主干/trunk_v2_covered_gloss_s14_s27.json \
  --anchors ../03_锚与主干/anchors_external_FROZEN_yunjiu_2026-10-15.json \
  --arms bare,covered --judge --repeat 3
echo "Copy newest runs/v2_*.jsonl to ../04_原始数据_runs/v2_external_frozen_*.jsonl"

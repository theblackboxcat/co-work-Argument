# 态度层 · 真实对话冷读 + 出价两枪 · runner（公开版）

| 脚本 | 实验 | 调用数 |
|---|---|---|
| `run_coldread.py` | 冷读：整场 + 三段 × {裸读 bare, 带结构 struct} × 2 轮（开放问题 + 一句追问） | 16（`--main-only` 4） |
| `run_bid.py` | 出价扫描：整场 × bare × 2 轮 × 3 rep；`--probe open`（不指定方向）/ `--probe both`（分别点名问 A、B） | 每枪 6 |

- 模型：dots3-note-prev · temperature 0.2 · max_tokens 1600 · thinking disabled。不重试，失败就停。
- key **只**从环境变量 `DOTS3_API_KEY` 读，不写文件。仓库内无 key、无 config.json。
- `lib/providers.py` 与 `02_脚本/lib/providers.py` 是同一份；`trunk/` 是 auth B（与 `03_锚与主干/trunk_v2_covered_gloss_s14_s27.json` 逐字节相同），只给 struct 读者用。
- **私人语料不在仓库内。** `dialogue/` 只有占位说明；没有转写，两个脚本会直接退出。冷读包里的 `rendered_prompts/`（含对话全文）也不公开。
- 公开的只有去引文的摘要：`04_原始数据_runs/stance_coldread_20261017/summary_stance_coldread_bid_20261017.json`。原始读数（raw jsonl、readings md、带引文的粗筛 json）大量引用对话原文，只留作者本地。
- 设计：`00_结论/设计_态度层_真实对话冷读_2026-10-17.md`；结算：`00_结论/结算_态度层真实对话冷读与出价两枪_2026-10-17.md`。

```bash
export DOTS3_API_KEY=...
python3 run_coldread.py --dry-run --main-only   # 不联网自检（仍需 dialogue/ 下有文件）
python3 run_coldread.py                          # 16 次
python3 run_bid.py --probe open                  # 第一枪
python3 run_bid.py --probe both                  # 第二枪
```

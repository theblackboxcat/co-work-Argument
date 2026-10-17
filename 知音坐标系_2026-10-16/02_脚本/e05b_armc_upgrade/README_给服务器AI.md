> **公开仓库版说明（2026-10-17）**：下面是当时交给服务器 AI 的原交接文字，保留作复现记录。公开版有两处不同：
> 1. key **只**从环境变量 `DOTS3_API_KEY` 读；`run_*.sh` 不再生成 `config.json`，文中「cp config.example.json config.json 填 key」一类说法作废。
> 2. `PRIVATE_anchors/anchors_e05b_seq_retest.json`（E05b／E05a／X01 锚原文）**不在公开仓库内**，见 `PRIVATE_anchors/README_不入库.md`。没有它脚本会直接退出。
> 设计、报告、结算文档在 `../../00_结论/`；回传结果（decision／summary）在 `../../04_原始数据_runs/`。

# README · E05b Arm-C 升级 · elicitation 判别（给能连 dots3 的服务器 AI）

> 要测：不发命令，E05b 的互认能不能被引出来，并且和 X01（标签复读）、E05a 分得开。  
> 本包**无 API key**；不冻任何东西、不关 E7。

## 做什么

每个锚每个 rep 两次独立调用：
- **Turn1**：auth B 定位，`COVERED_SYSTEM` 与 CTRL 包**字节相同**（启动前会校验 sha）。
- **Turn2**：三问中性探针，只给锚原文，**看不到** Turn1 的结果，也不带 trunk 释义。

3 锚（E05b／E05a／X01）× 3 rep × 2 轮 = **18 次实验调用**（另有 1 次连通性 ping）。model 和参数与 CTRL 相同（temperature 0.2 · max_tokens 700 · thinking disabled）。

## 跑

```bash
cd E05b_ArmC升级_外传包_2026-10-17
DOTS3_API_KEY='你的key' ./run_armc.sh
```

也可以 `cp config.example.json config.json` 在本地填 key，再执行 `./run_armc.sh`。  
启动前会自动检查：没有硬编码 key · run_v2.py／COVERED_SYSTEM 的 sha 与 CTRL 一致 · 没有 dual-bias 段 · 探针里没有节点名或禁词。任何一项不过就直接退出。

## 判定（预登记，只看 Turn2）

> scorer 给出的 verdict 只是**粗筛**；最终判断要等结果回传后，在 box 上细读 Turn2 rationale 再定（见设计 §4b）。你只管如实跑完、回传三件。

mutual 的定义：(c) 选 1，**且** (a) 的引文能在锚原文里逐字找到。

| | |
|--|--|
| PASS | E05b mutual ≥2/3 且 X01 选「2 标签复读」≥2/3 且 E05a mutual ≤1/3 |
| FAIL | E05b mutual ≤1/3，或任一负样本 mutual 次数 ≥ E05b |
| INC | 其他（含样本不全、解析失败） |

Turn1 定位数字单独列出，不进判定。(b) 的自由文本原样保留，由作者映射地址。

## 回传（只回 out/ 三件）

`out/armc_raw_<TS>.jsonl` · `out/armc_scores_<TS>.json` · `out/armc_summary_<TS>.md`  
脚本跑完会打印 zip 命令。**不要**回传 `config.json` 或 `PRIVATE_anchors/`。API 失败时不要补数字。

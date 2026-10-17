> **公开仓库版说明（2026-10-17）**：下面是当时交给服务器 AI 的原交接文字，保留作复现记录。公开版有两处不同：
> 1. key **只**从环境变量 `DOTS3_API_KEY` 读；`run_*.sh` 不再生成 `config.json`，文中「cp config.example.json config.json 填 key」一类说法作废。
> 2. `PRIVATE_anchors/anchors_e05b_seq_retest.json`（E05b／E05a／X01 锚原文）**不在公开仓库内**，见 `PRIVATE_anchors/README_不入库.md`。没有它脚本会直接退出。
> 设计、报告、结算文档在 `../../00_结论/`；回传结果（decision／summary）在 `../../04_原始数据_runs/`。

# README · 给能连 dots3 的服务器 AI · E05b dual-stop 杀臂

> **实验**：压同一 rep 的 S14+S20 共现（auth B + 同址摄取加压）  
> **基线**：Step3 INC `20261017_142455` · dual-stop **0/3**（信号散在不同 rep）  
> **回传**：作者 → **Ollie**（jsonl + summary + decision）  
> **本包无**真实 API key · **锁一句**：auth B 不变；勿因本跑单独把 Arm-B 冻进授权

---

## 1. 要打穿什么

懂人／知音共址在 E05b 上最硬的一枪：**同一 covered rep** 同时点到 S14（共享停靠／过程）+ S20（知音对齐／结果）。  
本臂 **不换 trunk**，只在 locate prompt 加压：见互认摄取语（「是的」「我刚就想说」等）→ 默认双停；单选须写理由。

设计全文：`docs/设计_E05b_dualstop杀臂_2026-10-17.md`。  
**CTRL 跳过**（省 API；基线用 Step3 dual 0/3）。

---

## 2. PASS / FAIL / INC（本臂）

| | |
|--|--|
| **PASS** | dual-stop **≥2/3** |
| **FAIL** | dual-stop **0/3** 且 uptake=no |
| **INC** | dual **1/3** 或混杂 |

哨兵 E05a／X01 **必须**并列报 S14 **与** S20 过触发（`docs/草案_哨兵口径扩S20_DRAFT_2026-10-17.md`）。负样本 S20 稳贴 → 记给日后冻边界谈；**不否决**本臂 PASS。

---

## 3. API key

```bash
cp config.example.json config.json   # 填 api_key
# 或: export DOTS3_API_KEY='...'
```

默认 `base_url=http://note3-prev-api.askdiandian.com` · `model=dots3-note-prev`  
**勿**把 key 写进回传包。

---

## 4. 一键跑

```bash
cd /path/to/E05b_dualstop杀臂_外传包_2026-10-17
cp config.example.json config.json   # 填 key
chmod +x run_dualstop.sh
./run_dualstop.sh
# TIMEOUT=120 ./run_dualstop.sh
```

约 covered×3 = **9** 次调用。

---

## 5. 回传三件套

```bash
TS=看 out/ 时间戳
zip -j E05b_dualstop_results_${TS}.zip \
  out/e05b_dualstop_${TS}.jsonl \
  out/summary_E05b_dualstop_${TS}.md \
  out/decision_E05b_dualstop_${TS}.json
```

**不要**回传 `config.json`／PRIVATE_anchors。

---

## 6. 目录

```
run_dualstop.sh
scripts/run_v2.py          ← COVERED_SYSTEM 已加压
scripts/score_dualstop.py  ← dual 闸 + S14∧S20 哨兵
trunk/trunk_v2_covered_gloss_s14_s27.json   ← 仅授权 B
PRIVATE_anchors/  docs/  out/  config.example.json
```

依赖：Python 3.8+ 标准库 + 能访问 dots3。

---

*外传包 · dual-stop 杀臂 · 跑完回 Ollie*

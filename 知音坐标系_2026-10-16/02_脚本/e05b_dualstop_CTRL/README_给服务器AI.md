> **公开仓库版说明（2026-10-17）**：下面是当时交给服务器 AI 的原交接文字，保留作复现记录。公开版有两处不同：
> 1. key **只**从环境变量 `DOTS3_API_KEY` 读；`run_*.sh` 不再生成 `config.json`，文中「cp config.example.json config.json 填 key」一类说法作废。
> 2. `PRIVATE_anchors/anchors_e05b_seq_retest.json`（E05b／E05a／X01 锚原文）**不在公开仓库内**，见 `PRIVATE_anchors/README_不入库.md`。没有它脚本会直接退出。
> 设计、报告、结算文档在 `../../00_结论/`；回传结果（decision／summary）在 `../../04_原始数据_runs/`。

# README · dual-stop CTRL · 拆命令 vs 结构

> **杀什么**：加压臂机器 PASS（dual 3/3）是不是只靠 prompt 命令？  
> **怎么杀**：同 auth B／同锚／**去掉** dual-bias 段 · covered×3 ≈9 calls  
> **对照**：加压 `20261017_144249` dual 3/3 · X01 曾压出 dual  
> **锁一句**：不冻 Arm-B · 不关 E7 · 不宣称知音已证 · 本包无真实 key

---

## 读法（跑完看 decision）

| CTRL E05b dual | 含义 |
|----------------|------|
| **≥2/3** | 加压不是唯一原因 → 结构叙事可重开 |
| **0/3（或≤1/3）** | 加强「Δ=prompt 命令」· 证据降权坐实 |
| 另报 | X01 dual（无加压基线）· 哨兵 S14∧S20 · 对照表 |

`negative_dual_veto`：加压臂若在 X01 压出 dual → 否决「结构读懂」（加压已触发）；本 CTRL 记录无加压时 X01 是否仍 dual。

---

## 跑

```bash
cd /path/to/E05b_dualstop_CTRL_外传包_2026-10-17
cp config.example.json config.json   # 填 api_key 或 export DOTS3_API_KEY
chmod +x run_ctrl.sh && ./run_ctrl.sh
```

`run_ctrl.sh` 启动前会断言 COVERED_SYSTEM **不含** dual-bias。

---

## 回传三件套

```bash
zip -j E05b_dualstop_CTRL_results_${TS}.zip \
  out/e05b_dualstop_CTRL_${TS}.jsonl \
  out/summary_E05b_dualstop_CTRL_${TS}.md \
  out/decision_E05b_dualstop_CTRL_${TS}.json
```

勿回传 `config.json`。结果交作者 → **Ollie**。

---

*CTRL 外传包 · 2026-10-17*

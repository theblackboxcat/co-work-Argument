> **公开仓库版说明（2026-10-17）**：下面是当时交给服务器 AI 的原交接文字，保留作复现记录。公开版有两处不同：
> 1. key **只**从环境变量 `DOTS3_API_KEY` 读；`run_*.sh` 不再生成 `config.json`，文中「cp config.example.json config.json 填 key」一类说法作废。
> 2. `PRIVATE_anchors/anchors_e05b_seq_retest.json`（E05b／E05a／X01 锚原文）**不在公开仓库内**，见 `PRIVATE_anchors/README_不入库.md`。没有它脚本会直接退出。
> 设计、报告、结算文档在 `../../00_结论/`；回传结果（decision／summary）在 `../../04_原始数据_runs/`。

# README · 给能连 dots3 的服务器 AI · E05b Step3 外传包

> **实验**：E05b 互认通道复测（执行单 Step3 · 在 Step1 计分诚实 + Step2 DRAFT 同址摄取口径下）  
> **日期**：2026-10-17 · Asia/Shanghai  
> **回传对象**：作者 → **Ollie**（结果三件套）  
> **本包不含**真实 API key

---

## 1. 这是什么实验

在**授权口径 B**（trunk `trunk_v2_covered_gloss_s14_s27.json` · v2+F3 · S14 demote）下，对主靶锚 `E05b_alignment_confirmation` 跑 **covered × 3**，并用廉价哨兵 `E05a` / `X01` 看 S14 过触发。

评分采用 Step2 **DRAFT**「S14 线索②同址摄取」：看行为上是否点到**同一停层地址**；**并列** HARD capped（exact／J）与仪器诚实（dual-stop／通道可见）。  
**不是**把 Arm-B／v3 冻进授权；**不是**宣称「知音」整体已证；**不是**关闭 E7。

细节见 `docs/` 内执行单、草案、旁报、附页、猛攻报告。

---

## 2. 成功标准（PASS / FAIL / INC）

来自 `docs/草案_S14线索②同址摄取_DRAFT_2026-10-17.md`（未冻）：

| 判据 | 含义 |
|------|------|
| **PASS** | 双方（或模型对双方回合的定位）能点到**同一停层地址**；行为可见同址摄取；仪器诚实指标显示通道存在，**不只** capped exact |
| **FAIL** | 仅一问一答、内容各说各话；或持续 S20 吸收且无法点到共享停层；**禁止**仅凭 `exact=0` 判 FAIL |
| **INC** | 通道迹象与过触发并存、或 API／样本不足；副作用恶化记 INC，**仍不冻** |
| **Gate** | `exact=0 under HARD cap ≠ channel fail` · J 天花板：3-node gold × HARD 1–2 → **J≤2/3** |

`scripts/score_step3.py` 会按上表自动写 `decision_*.json` 的 `verdict`。你仍须在 summary 里人工扫一眼 rationale，确认没有明显胡说。

---

## 3. 如何设置 API key（二选一）

**方式 A（推荐）**

```bash
cp config.example.json config.json
# 编辑 config.json，把 "api_key": "" 填成真实 key
# 勿把 config.json 提交进 git / 勿回传含 key 的 zip
```

**方式 B**

```bash
export DOTS3_API_KEY='你的key'
# run_step3.sh 会临时写出 config.json（仍勿提交）
```

- 默认 `base_url`：`http://note3-prev-api.askdiandian.com`
- 默认 `model`：`dots3-note-prev`
- **永远不要**把真实 key 写进 README、summary、decision、或回传包

---

## 4. 一键命令（复制粘贴）

```bash
cd /path/to/E05b_Step3_外传包_2026-10-17

# 1) 配 key（见上一节）
cp config.example.json config.json   # 然后填 api_key
# 或: export DOTS3_API_KEY='...'

# 2) 跑（covered ×3 · 约数分钟，视 API 延迟）
chmod +x run_step3.sh
./run_step3.sh

# 可选：拉长超时
# TIMEOUT=120 ./run_step3.sh
```

脚本会：probe → `run_v2.py` covered×3 → 复制 jsonl 到 `out/` → `score_step3.py` 写 summary + decision。

**默认加载授权 B trunk。** 包内 `trunk/OPTIONAL_DRAFT_ONLY_*.json` **不要**当官方主跑，除非作者另拍诊断臂。

---

## 5. 跑完回传什么（zip 这三件）

```bash
TS=看 out/ 里实际时间戳
zip -j E05b_Step3_results_${TS}.zip \
  out/e05b_seq_retest_${TS}.jsonl \
  out/summary_E05b_Step3_${TS}.md \
  out/decision_E05b_Step3_${TS}.json
```

把该 zip 交给作者，请作者转给 **Ollie**。

**不要**回传：`config.json`、整包源码、PRIVATE_anchors（除非作者只要备份）。

---

## 6. 禁止事项（硬）

1. **禁止**把 Arm-B／窄边界／v3／v4 **冻结**进授权 B  
2. **禁止**宣称「知音／共址整体已证」  
3. **禁止**顺带关闭 **E7**  
4. **禁止**在 API 失败时**编造** hit／J／exact 数字 → 标 INC／`api_ok=false`  
5. **禁止**把 `PRIVATE_anchors/` 提交公开仓库  
6. **禁止**改 csh／sdia／重开 NN 微观（本包无那些脚本）

---

## 7. 目录速览

```
README_给服务器AI.md          ← 你在读
交接_需要你跑什么_一页.md      ← 给人类作者的交接页
config.example.json           ← 复制为 config.json
run_step3.sh                  ← 入口
scripts/run_v2.py             ← 主跑
scripts/score_step3.py        ← HARD + 仪器诚实 + DRAFT 判定
scripts/lib/providers.py      ← dots3 适配
trunk/trunk_v2_covered_gloss_s14_s27.json   ← 授权 B
trunk/OPTIONAL_DRAFT_ONLY_*.json            ← 诊断 only，默认不用
PRIVATE_anchors/              ← 私人锚 + WARNING
docs/                         ← 执行单／草案／旁报／附页／猛攻报告
out/                          ← 结果输出
```

---

## 8. 依赖

- Python 3.8+（标准库即可：urllib／json；**无** pip 安装需求）
- 能访问 dots3 `base_url` 的网络

---

*外传包 · 给服务器 AI · 跑完结果回 Ollie*

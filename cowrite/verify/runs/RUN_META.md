# RUN_META · VERIFY 臂曲线锁定

> **写入时刻**：2026-10-12 Asia/Shanghai（CST）  
> **性质**：跑前/跑后常量锁定 · 非 claim 升级

```text
model_endpoint: dots3 / dots3-note-prev @ <API_HOST>
temperature: 0.3
thinking: disabled
feature_impl: v3/classifier.py + params.json (params.json version 3.8)
label_set: genre_proxy_P_vs_S (corpus_genre as P-proxy, corpus_S as S-proxy)
label_batch: holdout_n30_each_seed20261012
delta_stop: 0.02 AUC x 2 consecutive steps
n_holdout: 60 (30 S-proxy + 30 P-proxy; seed 20261012)
arm_instantiation: approximate prompt-ablation (see arm_mapping below)
```

## Arm mapping（自代码）

| Arm | 工程侧实例化 | 清洁度 |
|-----|-------------|--------|
| **A** bare | 仅分类指令系统提示（无 SKILL / 无 policy / 无 attention / 无 civility） | **近似消融**：runner 的 `baseline` 实际是 SKILL.md+WORKFLOW.md，**不是**裸模型；本 VERIFY 故意用更裸的 A |
| **B** iron+policy | `policy.build_system` ← `USE_V3`/`SKILL_v3.md` + 铁律/禁令/模式（`bans.py`）+ classify-only 后缀 | 对应 runner `--arm v3` 的策略核；**关闭** live attention 状态机与 civility judge 调用 |
| **C** full | B + 文明条款 C1–C13 文本 + 注意力工作流说明（CODING/段末/⊘） | **近似**：注意力为提示词注入，**不是** `server.py` `/api/attention` 光标状态机；未跑 `judge.judge_civility` 二次调用 |
| **D** | **未跑** | 可选结构臂；禁止用其冒充提示词堆叠有效 |

原生开关摘录：

- `USE_V3` 文件存在 → `server.py` 走 `v3/policy.py` + `v3/attention.py`
- `runner.py --arm baseline|v3`；`--civility` / `--judge` 可选
- 干净 A/B/C 三档二进制开关**不存在** → 本跑标记为 **approximate prompt-ablation**

## Feature ceiling（同实现离线，非本臂新发明锚点对照）

| 对照 | n | mean scores | AUC |
|------|---|-------------|-----|
| cross-lang S vs genre | 1200 / 852 | 0.1309 / 0.1373 | **0.4921** |
| same-lang ZH novel vs prose | 800 / 572 | 0.1529 / 0.1625 | **0.4596** |

已发表锚点（不得覆盖）：同语言 **0.489** · 跨语言 **0.523**（见 `证据锚点_已发表数字.md`）。

## 标签批次隔离

- **主评测批**：genre_proxy holdout（本 RUN）——与作者反馈表**分开**。
- **作者反馈批**（不合并进本 AUC）：`作者标注.json` 流派 10 + 非P 12 + v32 6 = 28；口径=接受/太弱/太强/不对（输出质量），**不是** P/M/S 真值。
- 按钮沉默批（probe.jsonl）未用于本臂 AUC。

## 禁止勾选

- [x] 未声称 understanding 已达成
- [x] 未写 CSH 否证提示词
- [x] 未开 S3 / 未升 SDIA keepable
- [x] 未合并不同标注批
- [x] 未用 Arm D 冒充堆 prompt

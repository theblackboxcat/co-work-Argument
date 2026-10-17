# 就绪单 · E05b 互认复测 Step3 · BLOCKED 待 laptop · 2026-10-17

> **【UNBLOCKED → 已跑 · 2026-10-17】**：原 laptop／dots3 BLOCKED 已由 **server handoff pack** 解阻；实跑 ts=`20261017_142455` · verdict **INC** · E05b **仍待补** · E7 **仍开**  
> 正式报告：`实验报告_E05b互认复测_按序补全_2026-10-17.md` · 结算：`结算_E05b按序复测_Step3_INC_2026-10-17.md` · raw：`04_原始数据_runs/e05b_seq_retest_20261017/`  
> 下方正文保留历史 BLOCKED 记录（备查）；**勿**再按「待 laptop」开跑。

---


> **地位**：Step3 实跑就绪单 · **BLOCKED** · **无编造数字** · **≠** 关 E7 · **≠** 冻 Arm-B／v3  
> **时区**：Asia/Shanghai  
> **上游**：`执行单_互认按序补全_E05b到E7_2026-10-17.md` · `草案_S14线索②同址摄取_DRAFT_2026-10-17.md` · `旁报_仪器诚实计分_E05b到E7_2026-10-17.md` · `实验报告_E05b互认通道猛攻_2026-10-17.md`  
> **作者授权**：已明示「开跑 Step3 E05b互认复测」——缺的是 **dots3／主机**，不是授权。

---

## 0. BLOCKED 状态（历史实查 · 已由 server handoff 越过）

| 项 | 结果 |
|----|------|
| 作者「开跑」 | **已授权** |
| Step1 计分诚实 | 已就位 |
| Step2 DRAFT 同址摄取 | 已就位（评分口径变更；不换冻结 trunk） |
| box → dots3 (`http://note3-prev-api.askdiandian.com`) | **超时／不可用**（15s curl POST 未回；父代理确认 timeout） |
| laptop `79af394b-38e2-4cbc-8049-0799d8758b58` | **connected:false**（父代理确认） |
| 本轮 jsonl／数字 | **未产生** · **禁止编造** |

**解除条件（任一即可开闸实跑）**

1. laptop 重连（`ListMachines` 显示该机 `connected:true`）且本机 dots3 可达；或  
2. box 到 dots3 的 API 恢复（probe／短 chat 在合理超时内成功）。

**向作者要的 unblock 一句**：请重连 laptop（或确认 dots3／VPN 可用）后，再说一次「继续 Step3」或「开跑」。

---

## 1. 本复测设计（就绪 · 未跑）

| 项 | 锁定 |
|----|------|
| 授权 trunk | `03_锚与主干/trunk_v2_covered_gloss_s14_s27.json`（**auth B · v2+F3 · S14 demote**） |
| Arm-B／v3／v4 | **不加载为官方**；`06_新包核验与续证/e05b_push_20261017/trunk_DRAFT_s14s20_boundary_narrow.json` **仅**若作者另拍诊断臂才旁路，且标 DRAFT、数字与官方分列 |
| Step2 加载方式 | **默认：仅评分／pass-fail 口径变更**（同址摄取 DRAFT）；**不**换冻结 trunk |
| 臂 | covered（主）；可选廉价哨兵同批 |
| 锚 | **主靶** `E05b_alignment_confirmation`；**哨兵** `E05a_huaxing_theory_monologue`、`X01_dialogue_register_label_paraphrase_s07` |
| n | covered × **3**（与猛攻同；API 脆则 E05b 至少 n=3） |
| 锚源 | `04_原始数据_runs/anchors_B_retest_filtered.json`（或同批过滤子集） |
| 配置 | `02_脚本/config.json`（dots3；**勿提交／勿 zip**） |
| 主机优先 | ① laptop（历史猛攻可用）② box（仅 API 可达时） |

### 1.1 DRAFT 互认 pass／fail（评分口径 · 未冻）

| | 判据 |
|--|------|
| **PASS** | 双方（或模型对双方回合定位）能点到 **同一停层地址**；行为可见同址摄取（确认对方所指／同节点词汇呼应）；仪器诚实指标显示通道存在，**不只** capped exact |
| **FAIL** | 仅一问一答、内容各说各话；或持续 S20 吸收且无法点到共享停层；**禁止**仅凭 exact=0 判 FAIL |
| **INC** | 通道迹象与过触发并存、或 API／样本不足无法判；副作用恶化记 INC／副作用栏，**仍不冻** |
| **平行** | Arm-C／S13 = 平行证据；定位不出 S13 ≠ 互认命题层不存在 |

**Gate**：`exact=0 under HARD cap ≠ channel fail` · J 天花板注：3-node gold × HARD 1–2 → **J≤2/3**。

### 1.2 仪器诚实必列表（跑完后填；本轮全空）

| 列 | 本轮 |
|----|------|
| auth exact／J（HARD 1–2） | *未跑* |
| node hits S14／S20／S13 | *未跑* |
| dual-stop／uncapped／通道可见 | *未跑* |
| elicit mutual／S13 短指（若廉价加 Arm-C） | *未跑／可选* |
| E05a／X01 S14 过触发 | *未跑* |
| E05b 待补→补全？ | **仍待补**（Step3 INC · 见正式报告；历史行曾写「无数字」） |
| E7 | **仍开** |
| 知音整体 | **不宣称已证** |

---

## 2. 解除后精确命令（laptop 优先）

假设工作根（laptop 历史资产；若路径漂移以本机镜像为准）：

```text
LAPTOP_ROOT = C:\Users\lenovo\Doubao\chats\2026-10-09\e05b_push_20261017\
# 或同步后的箱内根：
BOX_ROOT = /workspace/proj_20261009/论文资料_cowork/知音坐标系_2026-10-16/
```

### 2.1 预检

```bash
# 在目标主机上
date
# probe dots3（config.json base_url + api_key；勿打印密钥到日志仓库）
python3 - <<'PY'
import json, urllib.request
cfg=json.load(open("02_脚本/config.json"))  # 或 laptop 侧等价路径
url=cfg["base_url"].rstrip("/")+"/v1/chat/completions"
req=urllib.request.Request(url, data=json.dumps({
  "model": cfg["model"], "messages":[{"role":"user","content":"ping"}],
  "max_tokens": 8
}).encode(), headers={"Content-Type":"application/json",
  "Authorization":"Bearer "+cfg["api_key"]}, method="POST")
try:
  with urllib.request.urlopen(req, timeout=40) as r:
    print("probe_ok", r.status, r.read()[:120])
except Exception as e:
  print("probe_FAIL", type(e).__name__, e)
  raise SystemExit(2)
PY
```

### 2.2 过滤锚 → 临时子集（私锚文本可进临时文件；**不入库／不 commit**）

```bash
cd /workspace/proj_20261009/论文资料_cowork/知音坐标系_2026-10-16   # box；laptop 改等价根
python3 - <<'PY'
import json
from pathlib import Path
src = Path("04_原始数据_runs/anchors_B_retest_filtered.json")
want = {
  "E05b_alignment_confirmation",
  "E05a_huaxing_theory_monologue",
  "X01_dialogue_register_label_paraphrase_s07",
}
d = json.loads(src.read_text(encoding="utf-8"))
out = {"anchors": [a for a in d["anchors"] if a["id"] in want]}
assert {a["id"] for a in out["anchors"]} == want, out
dest = Path("04_原始数据_runs/anchors_e05b_seq_retest_TMP.不入库.json")
dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote", dest, "n=", len(out["anchors"]))
PY
```

### 2.3 主跑（auth B trunk · covered ×3）

```bash
TS=$(date +%Y%m%d_%H%M%S)
OUT="04_原始数据_runs/e05b_seq_retest_${TS}.jsonl"
python3 02_脚本/run_v2.py \
  --config 02_脚本/config.json \
  --trunk 03_锚与主干/trunk_v2_covered_gloss_s14_s27.json \
  --anchors 04_原始数据_runs/anchors_e05b_seq_retest_TMP.不入库.json \
  --arms covered \
  --repeat 3 \
  --timeout 90
# run_v2 默认写入 02_脚本/runs/v2_*.jsonl —— 跑完后复制／重命名到：
#   04_原始数据_runs/e05b_seq_retest_${TS}.jsonl
# （或改 runner 输出路径；勿把私锚／密钥提交进 git）
```

### 2.4 评分口径（Step2 DRAFT · 后处理 · 不改 trunk）

对每条 E05b covered rep，人工／脚本并列：

1. **HARD capped**：exact_set、Jaccard（官方列）  
2. **通道／同址摄取（DRAFT）**：nodes 是否同时点到共享停层意图（S14 过程 ↔ S20 结果共现？rationale 是否互相确认／同节点词呼应？）→ 记 `same_address_uptake=yes|no|unclear`  
3. **禁止**：`exact=0` 单独 → FAIL  
4. **哨兵**：E05a／X01 的 S14 出现率 → 副作用栏（抬升伴随过触发恶化 → INC／不冻）

可选廉价 Arm-C（两轮 elicit）仅作平行证据；**不**要求 localize 出 S13 才算通道活。

### 2.5 报告落盘（跑完后）

覆盖／续写：`00_结论/实验报告_E05b互认复测_按序补全_2026-10-17.md`  

必填：host · PASS／FAIL／INC（DRAFT 互认）· 仪器诚实表 · E05b 待补→补全？· 副作用 · **E7 仍开** · **不宣称知音已证** · 返回桥「懂人／知音共址」。

执行单 Step3 状态行改为：完成／INC／FAIL（按实数）；本就绪单标 **UNBLOCKED→已跑**。

---

## 3. 明确不做

- 编造 jsonl／hit 率／J  
- 冻 Arm-B／v3／v4 入授权 B  
- 改 csh／sdia；私锚入库；commit 密钥  
- 宣称知音整体已证；顺带关 E7  
- NN reopen

---

## 4. 返回 懂人／知音共址

本就绪单只服务 **L2 行为层共享地址** 上的 E05b 互认通道补全；本轮因主机／API **BLOCKED** 未产生证据。局部同址摄取复测 ≠ 知音整体已证；E7 另闸。

---

*执笔：Grok Bot · 2026-10-17 Asia/Shanghai · 历史 BLOCKED 正文保留 · 顶栏已标 UNBLOCKED→已跑 INC*

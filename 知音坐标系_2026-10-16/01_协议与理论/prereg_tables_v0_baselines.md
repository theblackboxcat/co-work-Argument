# Prereg tables · v0 baselines（check_trunk 复核）

日期：2026-10-15 CST  
Trunk：`trunk_v0.json`（N=27）  
Anchors：`anchors.json`（demo；**非**外部主证据）  
校验命令：`python3 check_trunk.py trunk_v0.json --anchors anchors.json` → exit 0  

地位：smoke / prereg 数字表；**不宣称理解已达成**；S3 CLOSED。

---

## 1. Layer distribution（v0 过浅）

| layer | count |
|-------|------:|
| trunk | 1 |
| branch | 4 |
| stop | 22 |
| **total** | **27** |

协议结论：v0 深度不足支撑「降层」检验；**v1 显式只测换枝 + 禁枝/contrast 边，不测降层**，直至主干加深（见 `协议_v1_…md`）。

### Branch sizes（直系子节点）

| parent_id | layer | #children |
|-----------|-------|----------:|
| T01_cn_modern_slice | trunk | 4 |
| B01_form_technique | branch | 4 |
| B02_motif_cluster | branch | 5 |
| B03_narratology | branch | 4 |
| B04_struct_exist_comm | branch | 9 |

---

## 2. Edges array（v0 存储态；层级多在 `node.parent`）

| kind | count |
|------|------:|
| parent | 2 |
| contrast | 2 |
| ban | 5 |
| **total** | **9** |

说明：`node.parent` 已有 26 条层级指针；`compact_trunk` 已把 parent+layer+gloss 送进 prompt。问题在于**协议未强制/计分边**。派生文件 `trunk_v1_parent_edges.json`（26 条 `{from:child,to:parent,kind:parent}`）与 v0 `edges` **零重叠**，可作加性合并候选。

---

## 3. Gold edge coverage（A01–A05）

判据：对每个 gold 节点对，检查 `trunk_v0.edges` 中是否存在任一边（无向匹配 `from`/`to`）。

| anchor | gold nodes | gold pairs | pairs with ≥1 edge | missing pairs |
|--------|------------|----------:|-------------------:|---------------|
| A01_transform | S03, S16 | 1 | 1 | — |
| A02_special_solution | S07 | 0 | 0 | — |
| A03_existential_plain | S05, S19 | 1 | 1 | — |
| A04_fractal_horror | S06 | 0 | 0 | — |
| A05_interpretive_vs_plot | S12, S17 | 1 | **0** | **S12↔S17** |

**缺口**：仅 A01、A03 的双点 gold 在 edges 中有覆盖；A05 的 S12+S17 **缺边**（notes 暗示 ban，但未写入 edges）。协议要求：用户重标外部锚时 **必须补全 gold.edges**。

---

## 4. Random baselines（精确复核）

定义（协议默认）：对每个锚，从 N 个 id **均匀无放回抽取 k=|gold| 个**；命中 = 抽中集合与 gold 交集非空。

### 4.1 用户原引 vs 精确值

| 用户原引 | 精确值 | 判定 |
|----------|--------|------|
| N=27, draw 2, P(≥1\|gold=2)=0.145 | 51/351 ≈ **0.145299** | 一致（四舍五入） |
| «draw 1: 0.074» | 若指 gold=1 且 **k=2**：2/27 ≈ **0.074074**；若协议 k=\|gold\|=1：1/27 ≈ **0.037037** | 用户数 = k=2 口径 |
| joint ≈ 1.7e-5（五锚模式） | 若 singleton 用 k=2：(51/351)³·(2/27)² ≈ **1.683145e-05**；若全程 k=\|gold\|：(51/351)³·(1/27)² ≈ **4.207864e-06** | 用户数 = singleton-k=2 口径 |

**Prereg 采用**：全程 **k=|gold|**（下表）。用户 0.074 / 1.7e-5 作为「若误用 k=2 for gold=1」的对照脚注保留。

### 4.2 Per-anchor（k=|gold|）

| anchor | \|gold\| | k | P(≥1 hit) |
|--------|------:|--:|----------:|
| A01_transform | 2 | 2 | 0.1452991453 |
| A02_special_solution | 1 | 1 | 0.0370370370 |
| A03_existential_plain | 2 | 2 | 0.1452991453 |
| A04_fractal_horror | 1 | 1 | 0.0370370370 |
| A05_interpretive_vs_plot | 2 | 2 | 0.1452991453 |

**Joint product**（独立假设）≈ **4.207864×10⁻⁶**

### 4.3 Reference closed forms（N=27）

| quantity | exact | ≈ |
|----------|------:|--:|
| P(≥1\|gold=2, k=2) | 1−C(25,2)/C(27,2)=51/351 | 0.145299 |
| P(≥1\|gold=1, k=1) | 1/27 | 0.037037 |
| P(≥1\|gold=1, k=2) | 2/27 | 0.074074 |
| joint k=\|gold\| pattern 2,1,2,1,2 | (51/351)³·(1/27)² | 4.207864e-06 |
| joint singleton-k=2（用户 ≈1.7e-5） | (51/351)³·(2/27)² | 1.683145e-05 |

---

## 5. Integrity（check_trunk）

| check | result |
|-------|--------|
| parent refs resolve | OK |
| no parent cycles | OK |
| edge endpoints exist | OK |
| edge kind ∈ {parent, contrast, ban} | OK |
| gold nodes ⊆ trunk | OK |
| exit code | **0** |

---

*数字由 `check_trunk.py` 生成；改 trunk/anchors 后请重跑并替换本表。*

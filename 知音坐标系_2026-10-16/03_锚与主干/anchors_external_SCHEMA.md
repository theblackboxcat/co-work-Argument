# anchors_external schema（空白模板说明）

配套文件：`anchors_external_BLANK.json`（`anchors: []`，由**用户**填写）。

**硬约束**

- 助手不得代写 `text`，不得代填 `gold`。
- 禁止把 trunk label 改写成近义句当作主证据锚。
- 复杂度下限：锚点须与真实对话语料节点同维，而非标签玩具复述。
- S3 CLOSED；不宣称理解已达成。

## `meta`

| 字段 | 含义 |
|------|------|
| `role` | 固定：用户冻结的外部定位锚，非树内容源 |
| `instructions` | 填写纪律（见空白 JSON） |
| `theory_lock` | generate≠commit；S3 CLOSED 等 |
| `schema_version` | `external_blank_v1` |
| `date_template` | 模板创建日 |

## `anchors[]` 每条字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 稳定锚 id，如 `E01_…`（用户自定） |
| `text` | string | **用户**从对话摘出的原文/同意公开的摘录；助手不代写 |
| `gold` | object | 用户标注的金标准小子图 |
| `gold.nodes` | string[] | trunk 白名单内的节点 id |
| `gold.edges` | object[] | `{from, to, kind}`，`kind ∈ {parent, contrast, ban}`；多节点 gold **必须**尽量补全边（协议要求 re-annotate 时补齐） |
| `source_ref` | string | 对话中的出处（卷/段/时间码等，用户自定粒度） |
| `date_excerpted` | string | 摘录日期 ISO，如 `2026-10-15` |
| `is_ban_sample` | bool | `true` = 干扰项/硬负例（近义标签冒充），用于排除近释义匹配；非随机噪声 |
| `notes` | string | 可选备注（为何选此锚、已知歧义等） |

## 字段形状示例（**无正文**；仅示结构）

下列 JSON 片段是**字段形状**说明，`text` 处为占位符，**不是**可跑的示范锚，也**不是**对任何 trunk label 的改写：

```json
{
  "id": "E00_SCHEMA_ONLY",
  "text": "<USER_PASTES_DIALOGUE_EXCERPT_HERE>",
  "gold": {
    "nodes": ["<trunk_id_1>", "<trunk_id_2>"],
    "edges": [
      {"from": "<trunk_id_1>", "to": "<trunk_id_2>", "kind": "ban"}
    ]
  },
  "source_ref": "<dialogue_locus>",
  "date_excerpted": "YYYY-MM-DD",
  "is_ban_sample": false,
  "notes": ""
}
```

干扰项示例形状（同样无改写正文）：

```json
{
  "id": "E00_INTERFERENCE_SCHEMA_ONLY",
  "text": "<USER_PASTES_NEAR_LABEL_PARAPHRASE_OR_CONFUSABLE_PASSAGE>",
  "gold": { "nodes": [], "edges": [] },
  "source_ref": "<constructed_or_dialogue>",
  "date_excerpted": "YYYY-MM-DD",
  "is_ban_sample": true,
  "notes": "hard negative: near-synonym of a stop label; correct behavior is miss or author-reject, not hit"
}
```

## 与 demo `anchors.json` 的关系

- `anchors.json`（`source: anchor_demo`）是后写演示锚，**不得**作理论验证主证据（见理论骨架 §10.4）。
- 主证据路径：用户填写本空白模板 → 冻结 → 再跑双臂。
- 旧字段 `gold_node_ids` 仅兼容 demo；外部锚统一用 `gold.nodes` + `gold.edges`。

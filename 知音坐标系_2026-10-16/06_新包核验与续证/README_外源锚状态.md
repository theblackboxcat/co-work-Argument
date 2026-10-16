# 外源锚状态（2026-10-15 freeze）

- `anchors_external_BLANK.json`：空模板（`anchors: []`），供日后另批填写。
- `anchors_external_DRAFT_from_yunjiu_2026-10-15.json`：冻结前草稿（见 `06_新包核验与续证/`）。
- **`anchors_external_FROZEN_yunjiu_2026-10-15.json`**：作者「好」授权冻结批（本目录 + 06/）。
  **13:23 更新**：E05 拆锚冻结——原 E05 superseded（不入主效应分母，保留溯源），新增 E05a（gold=S03）/ E05b（gold=S14+S20+S13，S13 保留）；D 段「是的！我刚就想说是内外。」经作者确认为云酒应答；主效应分母 = E01–E04 + E05a + E05b（6 锚）。
- `trunk_v2_covered.json`：基干未改。
- `trunk_v2_covered_gloss_s14_s27.json`：仅 S14/S27 gloss F3 补丁应用副本；sidecar 见 `06_…/gloss_patch_s14_s27_2026-10-15.json`。
- `06_新包核验与续证/实验补报_2026-10-15/trunk_v3_s14s20_sharpen_DRAFT.json`：**S14/S20 锐化 v3 草案（未冻结）**——仅 S14/S20 两条 gloss 变更（S14=过程态/S20=结果态 + 双向边界句）。16:41 试跑（`04_原始数据_runs/v3_s14s20sharpen_20261015_164100.jsonl`）：E05b-S14 0/3→3/3 达成，但 S14 对对话体过度触发（非 gold 出现 10 次），**v4 方向待作者裁**（补报 §6）。**17:36 更新**：作者选 A 已执行（v4 草案 `trunk_v4_s14_narrowed_DRAFT.json`）——**A 被数据否证**（E05a/X01 未收敛、主效应净劣化），建议回到 v3；E05a gold 复议 + v3 冻结两项待作者裁（补报：`00_结论/实验补报_v4_S14收窄试跑_A方案否证_2026-10-15.md`）。
- 私语料不得入公开 GH。S3 CLOSED；generate≠commit。

# 知音坐标系 · v1 协议与工具（无 key）

- `协议_v1_共享可寻址坐标系_小子图定位.md` — 主协议
- `理论骨架_知音树与定位_2026-10-15.md` — 含 §10 批判收紧、§11 指向 v1
- `demo_localize_dots3/check_trunk.py` — 校验 + 随机基线
- `demo_localize_dots3/trunk_v1_parent_edges.json` — 26 条 parent 边（与 v0 edges 零重叠，可选并入）
- `demo_localize_dots3/anchors_external_BLANK.json` + `anchors_external_SCHEMA.md` — **仅你填**外源冻结锚
- `demo_localize_dots3/prereg_tables_v0_baselines.md` — 可贴进 prereg 的表
- `anchors.json` — v0 演示锚（label 反写，**不作主证据**）

跑校验：`cd demo_localize_dots3 && python3 check_trunk.py --trunk trunk_v0.json --anchors anchors.json`

硬约束：外源锚文本与 gold 只由作者填写；generate≠commit；不宣称理解已达成。

# 顺序探针 · 先承重再建议（脚手架）

这是过程证据。承重草稿还不在，建议就不许出。对齐分工伦理里的顺序：先承重，再建议。设计笔记：`知音坐标系_2026-10-16/00_结论/设计_ReactiveWriting_先承重再建议_2026-11-05.md`。

生成不是提交。这道门在建议出现之前。接受或拒绝仍由 `cowrite/provenance/` 另记。本脚手架不写终稿，不打分。

这不是知音结论。不关闭 E05b／E7，不宣称知音／L2 已证，不授权新臂，不改 gold／frozen／AUC／CSH／SDIA。禁止把一行日志读成或写成作者判决。

## 记什么

一条 JSONL 是一次顺序检查。

`load_bearing_present` 只表示人的承重草稿在不在，不是模型打分：

- `false`：门必须是 `block`，`reason_code` 为 `missing_load_bearing`。
- `true`：门必须是 `allow`，`reason_code` 为 `ok_after_human_draft`。

`phase` 跟草稿在不在、建议有没有试过对齐，不能混写：

- `await_load_bearing`：草稿不在，建议还没试。
- `suggest_blocked`：草稿不在，建议试过，被挡住。
- `load_bearing_ready`：草稿在，建议还没出。
- `suggest_allowed`：草稿在，建议被放行。

`span` 只收 before／after 的 sha256（或空串）。不写正文，不写偏移。`notes` 最多 280 字，不要贴语料。私人语料不入库。

## 跑

不联网，不需要 key，不依赖 jsonschema（`requirements.txt` 未列该包；按 schema 手检）。

```bash
python3 cowrite/reactive_order/reactive_order.py --smoke
```

`--smoke` 重写 `cowrite/reactive_order/runs/smoke.jsonl`：一条假的挡住（`suggest_blocked`）和一条假的放行（`suggest_allowed`），再拒几条坏记录，然后打印 `OK`。`runs/` 已 gitignore。

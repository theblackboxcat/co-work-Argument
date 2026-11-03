# 决策点 provenance（脚手架）

这是过程证据。作者在建议出现的那一下，明示接受、拒绝、改后接受或丢弃。对齐 Zhang、Bu、Dhillon 2026《Who Owns the Text?》模式 5（Provenance at the point of decision / 决策点上的出处）。设计笔记：`知音坐标系_2026-10-16/00_结论/设计_WhoOwnsTheText_voice承重与provenance_2026-11-02.md`。

生成不是提交。日志只记下手选的那一下。预览与正文在决策点分开；本脚手架不实现终稿持久着色。

这不是知音结论。不关闭 E05b／E7，不宣称知音／L2 已证，不授权新臂，不改 gold／frozen／AUC／CSH／SDIA。禁止把一行日志读成或写成作者判决。

## 记什么

一条 JSONL 是一个决策点。`source` 是产出建议的模型或 skill id，不是作者身份。

`load_bearing_flag` 只由作者标，不是模型打分：

- `true`：这条建议碰到承重句，接受因此可审计。
- `false`：作者标成非承重。流畅、可替换的商品腔在决策时就与承重句分开。
- 缺省：未标。不是「非承重」，也不是判决。

`span` 只收偏移和 sha256（或空串）。不写正文。`notes` 最多 280 字，不要贴语料。私人语料不入库。

## 跑

不联网，不需要 key，不依赖 jsonschema（`requirements.txt` 未列该包；按 schema 手检）。

```bash
python3 cowrite/provenance/provenance_log.py --smoke
```

`--smoke` 重写 `cowrite/provenance/runs/smoke.jsonl`：一条假 accept（`load_bearing_flag=true`）和一条假 reject（`false`），然后打印 `OK`。`runs/` 已 gitignore。

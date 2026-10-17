# 实验摘要 · E05b dual-stop 杀臂 · 20261017_144249

> **突破向** · auth B + dual-stop 摄取加压 · **≠** 冻 Arm-B · **≠** 关 E7 · **≠** 知音整体已证
> **verdict**：`PASS` · E05b：`补全候选` · api_ok=True · CTRL=跳过

## 判定理由

dual-stop ≥2/3：授权 B 下过程(S14)+结果(S20)同 rep 共现。E05b 可主张通道在授权口径下可共现（仍是一条切片 ≠ 知音整体已证）。哨兵 S14/S20 另栏；不因此自动冻 Arm-B／关 E7。

## 主靶 E05b（covered）

| 列 | 值 |
|----|----|
| dual-stop S14+S20 | **3/3** |
| S14 / S20 / S13 | 3/3 / 3/3 / 0/3 |
| uptake (DRAFT) | yes |
| meanJ HARD | 0.667 |
| exact_set any | False |

## 哨兵（S14 **与** S20 · 扩口径）

| 锚 | gold | S14 过触发 | S20 过触发 | 附 |
|----|------|------------|------------|-----|
| E05a | S03 | 0/3 | 3/3 | — |
| X01 | S27 | 3/3 | 1/3 | false_align_excl reps=0 |

禁止仅凭 S14=0 宣称「哨兵干净」。

## 逐 rep（E05b）

- rep1: nodes=`S14_shared_stop,S20_zhiyin_align` dual=True J=0.6666666666666666 uptake=yes
  - rationale: 双方通过‘是的’‘我刚就想说’互认共停，且围绕‘化形’与‘内外映射’达成结构对齐，符合双停共现条件。
- rep2: nodes=`S14_shared_stop,S20_zhiyin_align` dual=True J=0.6666666666666666 uptake=yes
  - rationale: 双方互认共停（「哦我理解了」「是的！我刚就想说」），将「化形」的内外映射共识共址为过程（S14_shared_stop）与结果（S20_zhiyin_align），双停共现。
- rep3: nodes=`S14_shared_stop,S20_zhiyin_align` dual=True J=0.6666666666666666 uptake=yes
  - rationale: 段落中双方明确互认（「哦我理解了」「是的！我刚就想说」）并共同停靠于「化形」与「内外映射」的结构对齐，符合双停共现要求；S14 承载过程性共停，S20 承载知音对齐结果。

## 回传

1. 本 summary · 2. `decision_E05b_dualstop_20261017_144249.json` · 3. jsonl

*score_dualstop.py · Asia/Shanghai*

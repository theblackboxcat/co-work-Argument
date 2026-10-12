# S1h2_es_select_fix · 文档同步指针（2026-10-11）

> 本目录为 **box 文档镜像**，不含完整基因/训练日志/代码运行树。完整实验产物在用户本机。

## 本机源

- 路径：`%USERPROFILE%\Doubao\chats\2026-10-09\必要性重建_本地\S1h2_es_select_fix\`
- 含：`code/`、`genes/`、`logs/`（stdout + result_arm_*.json ×24 + `_DONE`）、`tune/`、`run_arm.py` 等

## 本目录已同步（文档向）

| 文件 | 说明 |
|------|------|
| `计划.md` | 预注册计划 |
| `报告.md` | 结案报告（easy 8/8 · main 4/8 · legacy 8/8） |
| `frozen/thresholds_S1h2.json` (+sha256) | 跑前冻结；sha `468defc9…0885`；lr=0.05 |
| `frozen/clean_seeds_Dx2.json` (+sha256) | Dx2 干净 8 籽 |
| `logs/summary_S1h2_science.json` | 科学汇总 JSON |

## 结论一句话

**修好的 ES 是合格尺子（easy 8/8）；主臂同预算 4/8 未过 →「同预算下进化未达」**；「BPTT vs 进化」轴在本预算获干净支持。**禁写「进化不可达」**。STOP（不开 E2/S3）。

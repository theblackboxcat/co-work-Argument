# 结果输出目录

`run_step3.sh` 会把下列文件写到本目录（时间戳后缀）：

1. `e05b_seq_retest_YYYYMMDD_HHMMSS.jsonl` — 原始 covered×3 记录
2. `summary_E05b_Step3_YYYYMMDD_HHMMSS.md` — 仪器诚实并列摘要
3. `decision_E05b_Step3_YYYYMMDD_HHMMSS.json` — PASS/FAIL/INC 机器可读

把这三件 zip 回传给作者 → Ollie。API 失败时**不要编造**数字；decision 会标 `api_failed` / `INC`。

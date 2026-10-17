# E05b dual-stop CTRL（去加压） · runner（公开版）

- 入口：`export DOTS3_API_KEY=... && ./run_ctrl.sh`。key 只从环境变量读，不落盘，仓库内无 key、无 config.json。
- 依赖：`scripts/lib/providers.py`（与 `02_脚本/lib/providers.py` 同一份）、`trunk/`（auth B，与 `03_锚与主干/` 同名文件逐字节相同）。
- 私人锚不在仓库内（见 `PRIVATE_anchors/README_不入库.md`），所以本目录可审阅、不可直接复跑。
- 结果：`04_原始数据_runs/e05b_dualstop_CTRL_20261017/`。
- 历史交接文字：`README_给服务器AI.md`（顶部有公开版差异说明）。

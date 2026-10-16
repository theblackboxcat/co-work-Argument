# 知音定位 · 理论验证包

日期：2026-10-15 CST  
地位：**理论 + smoke demo 验证包**，不是 VERIFY 主表结果；**不宣称理解已达成**。

## 这是什么

本包把「知音树 / 定位坐标系」的理论骨架、文献对照、实现差距整理，以及一个可在可达 dots3 端点的机器上重跑的 **localization smoke demo** 打成可携交付物。

- **包含**：理论 Markdown、短定位锚 demo、手建公共主干、可移植 CLI（vendored `providers.py`）
- **不含**：亲密私人 PDF 语料、真实 API key、历史试跑日志中的本机路径/key 痕迹

## 理论锁（Theory locks）

1. **缺口是组织 + 定位**，不是再堆记忆 / skills。私人语料若存在，只作**定位锚点**，不是树的内容源。
2. **generate ≠ commit**：模型只提议节点与边；作者手选/拒绝才是 commit；禁止自动提交进树。
3. **不宣称理解已达成**；S3 CLOSED；本包只演示「把定位落到显式树上」。
4. Agent 靠长期记忆/技能拟合 **不是** 知音路径；对照应是 bare 游荡 vs tree 贴干。

## 目录结构

```
交付_知音定位理论验证包_2026-10-15/
├── README.md                          ← 本说明
├── 理论骨架_知音树与定位_2026-10-15.md
├── 文献对照_树纲领是否已有_2026-10-15.md
├── 工作整理_识别实现与验证入口.md
├── 语料/
│   └── README.md                      ← 说明私人 PDF 故意不收录
└── demo_localize_dots3/
    ├── README.md
    ├── localize.py
    ├── config.example.json
    ├── lib/providers.py               ← vendored，无硬编码 key
    ├── trunk_v0.json
    ├── anchors.json
    ├── 结果_试跑.md
    └── runs/README.md
```

## 如何填配置并跑 localize.py

需要一台能访问 dots3 端点（`note3-prev-api.askdiandian.com`）的机器。

```bash
# 解压后
cd 交付_知音定位理论验证包_2026-10-15/demo_localize_dots3

cp config.example.json config.json
# 编辑 config.json，填入 api_key
# 也可：export DOTS3_API_KEY='你的key' 并保持 api_key 为空字符串

python3 localize.py
```

成功时会：

1. probe 端点  
2. 对每条 anchor 跑 **bare** 与 **tree** 双臂  
3. 写入 `runs/run_<时间戳>.jsonl` 与 `runs/summary.md`

失败（常见：内网超时）时：脚本与树仍保留；见 `结果_试跑.md`。勿把 `config.json` 提交到公开库。

## generate ≠ commit；不宣称理解

- 输出 JSON 含 `needs_author_commit: true`；本 demo **从不**自动改 trunk。
- 本包 **不证明** 理解已达成、VERIFY 主表提升、或记忆拟合 = 知音。
- 弱证明目标：脚本能在显式主干上做双臂定位提议。

## 隐私与安全

- 已剥离 API key；zip 排除 `config.json` 与 `__pycache__`。
- 亲密私人对话 PDF **未收录**；`语料/README.md` 仅保留概念层说明。
- 若自行跑通，注意 `runs/` 中不要提交未打码的 key。

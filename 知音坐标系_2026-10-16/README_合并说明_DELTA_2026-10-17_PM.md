# 合并进公开仓库用的这一份（DELTA · 2026-10-17 傍晚）

日期：2026-10-17（Asia/Shanghai）  
仓库：https://github.com/theblackboxcat/co-work-Argument  
本文件夹还没有执行 git 提交，也没有推送。

## 这是什么

上午的 DELTA 已经由 PR #6 合入 `main`，PR #7 合入了 paper v3（2026-10-17）和答辩 pptx。  
**本包是 PR #6 之后的公开增量**：今天下午的 E05b 三跑和 Arm-C 升级、ArmC2 设计（暂停）、回原命题、态度层冷读和出价两枪、两份 DRAFT、它们的 runner，以及更新后的证据链、夜间账本和现状白话。

本包里也带着上午已经在 `main` 上的文件（逐字节相同），覆盖回去不产生改动。`paper/` 换成论文 v4（`李逾凡_从词表不可分到门控结构中的目标维持_学术重写版v4_2026-10-17.docx`）和答辩 v2（`答辩_2026-10-17_v2.pptx`）。作者已决定：`main` 上 `paper/` 里此前的 3 个 docx 和 2 个 pptx 全部删除，论文只留这一份；`主要结果表.csv` 和 `研究二数据对齐说明_2026-10-14.md` 保留。根 `README.md` 的论文链接改指 v4。

合并方法：把 `知音坐标系_2026-10-16/**` 覆盖或追加进仓库已有的同名目录。不要新建平行目录。**不碰 csh/、sdia/、cowrite/。**

## 本包相对 main 的增量

### 00_结论（新增，除注明外）
- `实验报告_E05b互认复测_按序补全` · `结算_E05b按序复测_Step3_INC` · `就绪单_…Step3_BLOCKED_待laptop` · `执行单_互认按序补全_E05b到E7`：Step3 按序复测，INC。
- `设计_E05b_dualstop杀臂` · `实验报告_E05b_dualstop杀臂` · `结算_E05b_dualstop_PASS降权`：加压臂 3/3，降权。
- `实验报告_E05b_dualstop_CTRL` · `结算_E05b_dualstop_AB定案`：CTRL 0/3，坐实双停是 prompt 命令出来的。
- `设计_E05b_ArmC升级_elicitation判别` · `实验报告_E05b_ArmC升级` · `结算_E05b_ArmC_引出成立判别卡态度层`：不发命令引出内容层共址；判别卡在态度层。
- `设计_ArmC2_态度层判别`：纸面，暂停。
- `回原命题_共址已成立层与未成立层`。
- `设计_态度层_真实对话冷读`：抽象版，不含对话。
- `结算_态度层真实对话冷读与出价两枪`：**公开版**，按功能描述话轮，不引原句。
- `草案_哨兵口径扩S20_DRAFT` · `草案_S14线索②同址摄取_DRAFT` · `附页_计分诚实核检_E05b` · `收尾_2026-10-17_今日闸与下一步`。
- `现状白话_2026-10-17`（**修改**：换成傍晚版）。

### 01_协议与理论 · 账本_夜间（修改）
- `证据链_共享可寻址坐标系_2026-10-15.md`：补了 13:04 收尾闸一行。
- `账本_夜间/夜间自治_2026-10-17.md`：补了 13:04 收尾闸一条。

### 02_脚本（新增）
- `e05b_step3_seq_retest/` · `e05b_dualstop_killarm/` · `e05b_dualstop_CTRL/` · `e05b_armc_upgrade/`：四个外传包的 runner 原样（scripts、templates、trunk、config.example.json），只改了一处：`run_*.sh` **只**从环境变量 `DOTS3_API_KEY` 读 key，不再生成 `config.json`。`PRIVATE_anchors/` 只放占位说明。
- `stance_coldread/`：`run_coldread.py`（冷读 16 次）、`run_bid.py`（出价两枪）。`dialogue/` 只放占位说明：**私人语料不包含在本仓库中**。

### 04_原始数据_runs（新增）
- `e05b_seq_retest_20261017/` · `e05b_dualstop_20261017/` · `e05b_dualstop_CTRL_20261017/`：只放 decision json 和 summary md。
- `e05b_raw_jsonl_20261017_未公开说明.md` · `e05b_armc_20261017_已撤出说明.md`。
- `stance_coldread_20261017/`：`summary_stance_coldread_bid_20261017.json`（去引文的计数摘要和按功能归类的判读）和 `README_公开口径.md`。

## 结论口径（与现状白话一致）

- E05b 内容层共址：**不发命令就引出来了**（Arm-C）。
- 态度层：完整语境下，读者认得出确认落地的那一下和空确认；对双功能话轮（回应同时递出关系性出价）有稳定盲点。作者把它作为**动作边界**证据收进论文。
- auth B 结构在态度层是**负贡献**。
- NN micro：**idle，结论为负**。
- E05b 定位 dual：**待补**。E7 开。整体知音不宣称已证。

## 没有放进来的（纪律）

- 作者私人群聊的任何内容：转写、截图、密封判断、冷读包的 `dialogue/` 和 `rendered_prompts/`、`coldread_raw/readings`、`bid_raw/readings`，以及带引文字段的粗筛 json。
- 私人锚：`anchors_e05b_seq_retest.json`（E05b／E05a／X01 锚原文）、`anchors_B_retest_filtered.json`、`不入库_私人语料/`。
- 原始 jsonl：E05b 今日三跑、B 复测 `v2_B_retest_*.jsonl`、Arm-C 全部回传（raw／scores／summary）。它们都带锚原文的逐字引用。
- `02_脚本/config.json`（含 key）、`__pycache__`、NN 的 `cells_raw.*` 大表。
- `01_协议与理论/草案_S14线索②同址摄取_DRAFT_2026-10-17.md`：与 `00_结论/` 里的那份正文相同，只是链接写法不同，不重复放。

## 合并时还要做的两件小事

- 本说明在树内另有一份：`知音坐标系_2026-10-16/README_合并说明_DELTA_2026-10-17_PM.md`（上午那份 `README_合并说明_DELTA_2026-10-17.md` 保留不动）。
- 仓库根 `README.md` 末尾追加 `README_根目录追加段.md` 里的那一段。`README_根目录追加段.md` 本身、本文件夹根上的 `README_合并说明.md` 和 `现状白话.md` 都不提交。

## 复现时 key 放在哪

`export DOTS3_API_KEY=...`。仓库里没有 key，今天这批 runner 也不读写 `config.json`。

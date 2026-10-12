# 修订说明（2026-10-12）

相对输入包 `/workspace/uploads/github_upload_pack/` 中的 `manuscript.docx`。**未新开实验，未升级论断**；数字与 `supplementary/主要结果表.csv` / 正文锁定值一致。

## 1. 参考文献引用

| 项目 | 做法 |
|------|------|
| 原稿 | 正文为普通文本 `[n]` / `[n-m]`；XML 核查无上标 run、无 REF/SEQ 域 |
| 修订 | 为文献条目 `[1]`…`[30]` 各建书签 `ref1`…`ref30` |
| 交叉引用 | 正文引用改为 **Word `REF` 域**（`REF refN \h`），显示为**上标数字**；范围引用如原 `[1-2]`、`[26-27]` 拆成上标 `1-2` / `26-27`，两端分别 REF 到对应书签 |
| 跳转 | `\h` 使点击可跳到书签；打开后若域结果未刷新，可在 Word 中全选后 F9 更新域 |
| 折中说明 | **主路径已是域交叉引用 + 上标**，不是“仅上标无域”。域结果文本在生成时写入（如 `1`），与书签段落并存；未使用 SEQ 域自动编号 |
| 非引用方括号 | Wilson 区间、阈值带如 `[0.676, 1.000]`、`[3972, 4960]` **未**改成引用 |

## 2. 关键图（新建，非旧 v50/phase3）

按正文出现顺序编号（与“建议图题内容”一致，图号按阅读顺序）：

1. **图 1** 伴写代理轴：左栏已发表同语言 0.489 / 跨语言 0.523；右栏后续消融 0.5989 / 0.6528 / 0.5730；明确分栏、不得互相覆盖。
2. **图 2** 符号实验阈值平坦性示意：CV(log)=0.009，几何均值 4374，带 [3972, 4960]；条高取几何均值作示意，**非**伪造逐表面点估计。
3. **图 3** 目标实验组通过率：GRU 8/8、fair-RNN 0/8、指定寄存器 7/8、Nov 2/8、E2 1/8、E2b 3/8、ES 主 4/8 等；虚线组门 7/8；fair-RNN / E2b / ES 主标注 post-PDF/后续。

- 图题在图下；表题在表上（三线表样式）。
- 正文增加「见图 1 / 见图 2 / 见图 3」交叉指称；表题与附录保留「表 1–4」指称。
- 图文件另存 `figures/*.png`。

## 3. 排版

- 页边距改为 A4、四边约 2.5 cm。
- 分层：中英文标题 / 作者 / 单位 / 摘要 / 关键词 / Abstract / Keywords / 一级与二级标题 / 参考文献 / 附录。
- 中文正文首行缩进两字符（`firstLineChars=200`）；英文 Abstract 不缩进。
- 字体约定：中文宋体（标题黑体、作者楷体），西文 Times New Roman；表内约 9 pt。
- 去掉原稿表后多余空段；统一段距与行距；表为三线表（顶/底粗线、表头下细线、无竖线）。

## 4. 仓库链接（附录 B）

- 原稿：“仓库建立后可补永久链接”。
- 修订：写入可点击完整 URL  
  `https://github.com/theblackboxcat/co-work-Argument`  
  并说明仓库含 `manuscript/`、`supplementary/`、`figures/`、`README.md`；禁止用本地工作区路径作引用。

## 5. Claim boundary（未改动的边界）

- 不写「理解已达成」；CSH/符号结果仅旁证，不否证伴写提示词。
- 不写门控普遍必要 / 原理不可达 / 自主设定已证；S3 CLOSED 不重开。
- VERIFY/消融数字不覆盖已发表 0.489 / 0.523。
- fair-RNN / E2b / ES 修复结果标明后续/相对 PDF 增量。
- VOID 留在分母；组门 7/8。
- 参考文献仍只收已出版/标明预印本的方法文献。

## 6. 输出结构

```
github_upload_pack_fixed_2026-10-12/
  README.md
  CHANGELOG_修订说明.md
  manuscript/李逾凡_从词表不可分到门控结构中的目标维持.docx
  manuscript/李逾凡_从词表不可分到门控结构中的目标维持.md
  supplementary/主要结果表.csv
  figures/fig1_cowrite_auc_published_vs_ablation.png
  figures/fig2_symbol_threshold_flatness.png
  figures/fig3_goal_pass_rates.png
```

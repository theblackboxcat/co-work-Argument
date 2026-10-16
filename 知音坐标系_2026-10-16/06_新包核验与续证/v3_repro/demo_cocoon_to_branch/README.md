# demo_cocoon_to_branch — 信息茧 → 枝节点（最小可行性）

日期：2026-10-15（Asia/Shanghai）

## 这证明什么 / 不证明什么

| 证明 | 不证明 |
|------|--------|
| 兴趣茧（filter bubble / convergent feed）里的文本可被**粗聚类**并提议为可编辑的 branch/stop **草稿地址** | 完整认知图已建成 |
| 茧 ≈ **无意收敛的地址簇**；我们要的是可审计、可手改的枝 | 「理解已达成」或 S3 打开 |
| 流程类似「反编译应用 → 模块树」，但是对**概念枝** | 自动写入公共主干（trunk） |
| offline、无 API key、纯 stdlib 可跑通 | BERTopic 级语义质量 |

**论断锁**：generate ≠ commit；作者必须手选/拒绝；coverage over bans；树/DAG 是容器不是本体。

## 与「反编译」的类比

| 应用反编译 | 本 demo（概念枝） |
|------------|-------------------|
| 二进制 / APK | 茧内帖文 / feed 切片 |
| 函数 / 模块边界 | 兴趣子簇 → branch / stop 草稿 |
| 符号表草稿 | `{id, label, gloss, layer, parent_hint, form_cues[]}` |
| 人工确认后入库 | author commit 后才进共享坐标系 |

大数据与推荐茧已经在**无意中**生产收敛坐标；本样本只做 **extraction → draft**，把无意簇变成可覆盖、可对照的地址草案。

## 茧 ≈ 潜在枝集合

同一 bubble 内反复出现的表面标记（碎片、平原、元叙述、阐释↔情节…）就是覆盖规则下的 `form_cues`。簇越大越像 branch；紧而可指认的像 stop。`parent_hint` 指向既有 culture×era 主干枝（如 `B01_form_technique`），**仅提示，不自动挂边**。

## 怎么跑

```bash
cd demo_cocoon_to_branch
python3 cocoon_to_branch.py
```

输入：`sample_cocoon.json`  
输出：`branch_draft_v0.json`、`结果_可行性.md`

## 文件

| 文件 | 作用 |
|------|------|
| `sample_cocoon.json` | 16 条合成茧帖（现代主义形式×存在母题，中英混；假 user/feed id） |
| `cocoon_to_branch.py` | Jaccard 凝聚 + 家族线索 → 草稿节点 |
| `branch_draft_v0.json` | 运行产物 |
| `结果_可行性.md` | 一页结果 + 人工清单 |
| `开源对照.md` | 可放大的开源工具表 |

## 下一步放大（作者侧）

1. 导出自己的公开 feed / 书签 / 论坛切片（勿混私人云酒对话进树内容源）。  
2. 换 BERTopic `hierarchical_topics` 或 Top2Vec hierarchical topics。  
3. 人工 commit：改 label/gloss、补 contrast/ban 边、按覆盖规则写 form 线索。  
4. 再跑既有 `check_trunk` / 定位双臂协议。

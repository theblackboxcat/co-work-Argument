# NN-of-NN Phase-1（涌现检验玩具 · 第 1 期）

目的锁：区分「分层 NN 组织共址临界」vs「联想记忆复现 / 单层同等 / 假长上下文」。

## 一键复现

```bash
cd /workspace/proj_20261009/论文资料_cowork/知音坐标系_2026-10-16/02_脚本/nn_of_nn_phase1
pip install -r requirements.txt   # 若环境已有 torch/numpy/matplotlib 可跳过
python run_phase1.py              # 跑满网格 → 04_原始数据_runs/nn_of_nn_phase1_2026-10-17/
python analyze_phase1.py          # 变点 + 判定码 + 相图 + 中文报告
```

报告：`../../00_结论/实验报告_NN组织NN_第1期_2026-10-17.md`

## 主报口径

- 组织器：O-H（现代 Hopfield）、O-M（MLP 权重、不读键）、D（参数量匹配单层）
- Pad：仅 Pad-⊥；η：low / high
- 臂：main / B（测试时毁掉绑定）
- 临界：单变点分段常数 LS + 种子自助法 95% CI
- 键集：N=N_priv；Hopfield 有效温度 BETA=4.0（β_raw=BETA·√d）
- 臂 B：训练保留绑定，仅测试时 derangement 重绑

## 文件

| 文件 | 作用 |
|------|------|
| `config.py` | 锁定网格与超参 |
| `models.py` | 原子 / O-H / O-M / D / R |
| `run_cell.py` | 单格训练与评价 |
| `run_phase1.py` | 全网格 |
| `criticality.py` | 变点与形态比较 |
| `analyze_phase1.py` | 判定、图、报告 |

授权开工日：2026-10-17。

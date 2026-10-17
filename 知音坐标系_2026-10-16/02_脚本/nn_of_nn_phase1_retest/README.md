# NN-of-NN Phase-1 复测（Fail-Bind + R1）

相对第 1 期唯二改动：
1. 臂 B **硬销毁**绑定（错对线索 / n_priv=2 时随机单位线索；训测皆毁）
2. **组合效用 U**：`q=normalize(k_i*+k_j*)+ηε`，`y=P[v_i*;v_j*]`，`m=mass on {i*,j*}`

不覆盖 `nn_of_nn_phase1_2026-10-17/`。

```bash
cd /workspace/proj_20261009/论文资料_cowork/知音坐标系_2026-10-16/02_脚本/nn_of_nn_phase1_retest
python run_phase1.py
python analyze_phase1.py
```

报告：`../../00_结论/实验报告_NN组织NN_第1期复测_2026-10-17.md`

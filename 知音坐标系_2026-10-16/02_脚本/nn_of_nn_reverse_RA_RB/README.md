# NN-of-NN 反向／共形 R-A + R-B（2026-10-17）

Prereg：`../../01_协议与理论/prereg_反向共形_RA_RB_2026-10-17.md`  
作者授权开跑：2026-10-17（说「开」）。**不**声称 FROZEN；**不**赎回 E-pass；Fail-Bind H2 仍权威。

## 相对复测的改动

- **冻结继承**：组合 U、硬臂 B 路径、变点程序、O-H/O-M/D、网格 α/d。
- **R-A**：同 α 下同步设 N_priv(d)；主报 η=low, pad=none, β=4.0。
- **R-B(i)**：只扫组织 β∈{2,4,8}。
- **R-B(ii)**：只扫 exec_pad 进 R ∈{0,16,32}。
- **不**覆盖 `nn_of_nn_phase1_*` 原始跑。

## 复现

```bash
cd /workspace/proj_20261009/论文资料_cowork/知音坐标系_2026-10-16/02_脚本/nn_of_nn_reverse_RA_RB
python run_RA_RB.py      # → ../../04_原始数据_runs/nn_of_nn_reverse_RA_RB_2026-10-17/
python analyze_RA_RB.py  # → decision.json + plots + ../../00_结论/实验报告_NN组织NN_反向共形_RA_RB_2026-10-17.md
```

## 判定码（仅本包）

RA-pass / RA-fail / RB-pass / RB-fail / RA+RB-pack-pass / Pack-kill / H-lit-align / Instr-curve  
**不重开** E-pass。

"""R-A + R-B reverse/conformal package — prereg_反向共形_RA_RB_2026-10-17.md

Author authorized 开跑 2026-10-17. Does NOT redeem E-pass; Fail-Bind H2 remains
binding-causal authority. Outputs only to nn_of_nn_reverse_RA_RB_2026-10-17/.
"""
from pathlib import Path

BASE = Path("/workspace/proj_20261009/论文资料_cowork/知音坐标系_2026-10-16")
SCRIPT_DIR = BASE / "02_脚本" / "nn_of_nn_reverse_RA_RB"
RESULTS_DIR = BASE / "04_原始数据_runs" / "nn_of_nn_reverse_RA_RB_2026-10-17"
REPORT_PATH = BASE / "00_结论" / "实验报告_NN组织NN_反向共形_RA_RB_2026-10-17.md"

# Never write here
PARENT_PHASE1 = BASE / "04_原始数据_runs" / "nn_of_nn_phase1_2026-10-17"
PARENT_RETEST = BASE / "04_原始数据_runs" / "nn_of_nn_phase1_retest_2026-10-17"

# ---- Shared grid (prereg §4 / §6; same as retest) ----
D_LIST = [16, 32, 64]
ALPHA_LIST = [0.05, 0.1, 0.14, 0.2, 0.3, 0.5, 1.0]
ETA_LEVELS = {"low": 0.15}  # main slice only (prereg §4.1: η=low 为主切片)
SEEDS = [0, 1, 2, 3, 4]
ORGANIZERS = ["O-H", "O-M", "D"]
# Binding arm not reopened as main evidence (prereg §3 / §6.1)
ARMS = ["main"]
PADS_RA = ["none"]  # Pad 主报 none

# Model dims (frozen inherit)
D_V = 32
D_Y = 8
D_PAD = 16
BETA_DEFAULT = 4.0
N_PUB_MULT = 0.0

# Training (frozen inherit)
ADAM_STEPS = 250
ADAM_LR = 3e-3
BATCH_SIZE = 64
N_EVAL = 256
RIDGE_L2 = 1e-3

# Criticality (v2 / retest)
MIN_SIDE_POINTS = 2
BOOTSTRAP_B = 400
CI_LEVEL = 0.95
SAME_MORPH_ALPHA_REL = 0.20
SAME_MORPH_GAP_RATIO = (0.5, 2.0)

# R1 gate (prereg §6.1)
R1_CORR_CAP = 0.9

# ---- R-B knife levels (prereg §5; ≤3 incl. default; draft defaults) ----
# Knife (i): org β only (default 4.0 locked for knife ii)
BETA_ORG_LEVELS = [2.0, 4.0, 8.0]
# Knife (ii): irrelevant dims concatenated into readout input (0 = none / default)
EXEC_PAD_DIMS = [0, 16, 32]
# U change-point delay window vs m: ≤ 1 α-grid step (prereg §5.2 draft default)
RB_U_DELAY_ALPHA_STEPS = 1

# Sweep tags written into each cell
SWEEP_RA = "R-A"           # α-plane: beta=default, exec_pad=0
SWEEP_RB_I = "R-B-i"       # twist org β
SWEEP_RB_II = "R-B-ii"     # twist exec pad into R

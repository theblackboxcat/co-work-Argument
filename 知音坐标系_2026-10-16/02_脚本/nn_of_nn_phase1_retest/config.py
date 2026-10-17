"""Phase-1 retest (Fail-Bind + R1) — locked grid; outputs to separate run dir."""
from pathlib import Path

BASE = Path("/workspace/proj_20261009/论文资料_cowork/知音坐标系_2026-10-16")
SCRIPT_DIR = BASE / "02_脚本" / "nn_of_nn_phase1_retest"
RESULTS_DIR = BASE / "04_原始数据_runs" / "nn_of_nn_phase1_retest_2026-10-17"
REPORT_PATH = BASE / "00_结论" / "实验报告_NN组织NN_第1期复测_2026-10-17.md"
# Parent results — never write here
PARENT_RESULTS_DIR = BASE / "04_原始数据_runs" / "nn_of_nn_phase1_2026-10-17"

# Grid (same as phase-1 / prereg)
D_LIST = [16, 32, 64]
ALPHA_LIST = [0.05, 0.1, 0.14, 0.2, 0.3, 0.5, 1.0]
ETA_LEVELS = {
    "low": 0.15,
    "high": 0.80,
}
SEEDS = [0, 1, 2, 3, 4]
ORGANIZERS = ["O-H", "O-M", "D"]
ARMS = ["main", "B"]
PADS = ["none", "pad_perp"]

# Model dims
D_V = 32
D_Y = 8
D_PAD = 16
BETA = 4.0
N_PUB_MULT = 0.0

# Training
ADAM_STEPS = 250
ADAM_LR = 3e-3
BATCH_SIZE = 64
N_EVAL = 256
RIDGE_L2 = 1e-3

# Criticality (same as v2)
MIN_SIDE_POINTS = 2
BOOTSTRAP_B = 400
CI_LEVEL = 0.95
SAME_MORPH_ALPHA_REL = 0.20
SAME_MORPH_GAP_RATIO = (0.5, 2.0)

# Retest apparatus success: arm-B mean m < this fraction of main-arm m (same cell)
ARM_B_M_DROP_FRAC = 0.50
# Apparatus OK if this fraction of (d,α) cells on primary slice pass the drop
ARM_B_M_DROP_CELL_FRAC = 0.80

# R1 gate
R1_CORR_CAP = 0.9

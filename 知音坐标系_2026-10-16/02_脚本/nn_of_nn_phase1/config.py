"""Phase-1 NN-of-NN emergence toy — locked grid (anti-inertia main report)."""
from pathlib import Path

BASE = Path("/workspace/proj_20261009/论文资料_cowork/知音坐标系_2026-10-16")
SCRIPT_DIR = BASE / "02_脚本" / "nn_of_nn_phase1"
RESULTS_DIR = BASE / "04_原始数据_runs" / "nn_of_nn_phase1_2026-10-17"
REPORT_PATH = BASE / "00_结论" / "实验报告_NN组织NN_第1期_2026-10-17.md"

# Grid (pre-registered)
D_LIST = [16, 32, 64]
ALPHA_LIST = [0.05, 0.1, 0.14, 0.2, 0.3, 0.5, 1.0]
ETA_LEVELS = {
    "low": 0.15,   # noise std relative to unit-key
    "high": 0.80,
}
SEEDS = [0, 1, 2, 3, 4]
ORGANIZERS = ["O-H", "O-M", "D"]  # main report; O-P appendix only
ARMS = ["main", "B"]              # B = destroy binding at test
PADS = ["none", "pad_perp"]       # Pad-⊥ only for main

# Model dims
D_V = 32          # value dim
D_Y = 8           # probe / target dim
D_PAD = 16        # reserved pad dims for Pad-⊥
BETA = 4.0        # effective coeff on q·k; implemented as β_raw=BETA*√d_in so attn=softmax(BETA q·k_i) ≡ softmax(β_raw q·k/√d)
N_PUB_MULT = 0.0  # Phase-1: N = N_priv (load α=N/d); public distractors left for appendix

# Training
ADAM_STEPS = 250
ADAM_LR = 3e-3
BATCH_SIZE = 64
N_EVAL = 256
RIDGE_L2 = 1e-3

# Criticality
MIN_SIDE_POINTS = 2
BOOTSTRAP_B = 400
CI_LEVEL = 0.95
SAME_MORPH_ALPHA_REL = 0.20
SAME_MORPH_GAP_RATIO = (0.5, 2.0)

#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# moving5 扩种：n=20 → n=30（新增 seed 120-129）
#
# 【预注册式固定样本量，禁止 optional stopping】
#   一次性把样本量加到 n=30，中途不窥探显著性、不入 statistical stopping rule、
#   结果无论显著与否都如实登记入 number_registry.json。
#   当前 n=20 的 Welch p=0.0508 未达显著——本批次的目的不是"把它推过 0.05"，
#   而是把估计精度提高，让人能判断"方向到底是不是真的"。
#   预注册说明见 docs/PREREG_expand_n30_20261003.md
#
# 纪律：
#   - 与既有 n=20 批次落到同一目录（seed 不同、文件不冲突），保持同批同口径
#   - OMP_NUM_THREADS = ceil(24 核 / 4 路) = 6，防止线程超订（历史教训：超订 2.7 倍）
# ─────────────────────────────────────────────────────────────────────────────
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."

export PY="C:/Users/Lenovo/AppData/Local/Programs/Python/Python312/python.exe"
export OUT=results/env_diversity_moving5_n20
export N_EP=3000
export OMP_NUM_THREADS=6
export MKL_NUM_THREADS=6
export OPENBLAS_NUM_THREADS=6

mkdir -p "$OUT"
LOG="$OUT/run_all.log"

run_one() {
  local env=$1 mode=$2 seed=$3
  "$PY" scripts/run_env_diversity.py --env "$env" --mode "$mode" --seed "$seed" \
    --n_episodes "$N_EP" --out_dir "$OUT" >> "$LOG" 2>&1
  echo "$(date +%m-%d_%H:%M:%S) DONE $env $mode seed=$seed rc=$?" >> "$LOG"
}
export -f run_one
export PY OUT N_EP OMP_NUM_THREADS MKL_NUM_THREADS OPENBLAS_NUM_THREADS LOG

echo "=== moving5 expand n=20->n=30 START $(date +%m-%d_%H:%M:%S) seeds=120..129 P=4 OMP=6 ===" >> "$LOG"

# 4 路并行；每个种子内先 bc 后 pure，保证配对种子时间上相邻（抵消批次漂移）
for s in $(seq 120 129); do echo "$s"; done \
  | xargs -P 4 -I {} bash -c 'run_one moving5 bc_marl {}; run_one moving5 pure_marl {}'

echo "=== ALL_DONE_EXPAND_N30 $(date +%m-%d_%H:%M:%S) ===" >> "$LOG"

#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# E14 跨算法扩种：n=20 → n=30（四算法 iql/vdn/mappo/qmix，新增 seed 120-129）
#
# 【预注册式固定样本量，禁止 optional stopping】
#   一次性加到 n=30，中途不窥探、不停止，结果无论显著与否都如实登记。
#   目的不是"制造显著性"，而是给「效果强依赖底层算法」这条主论断
#   （C1：目前仅 QMIX 显著）一个更有检验力的证据基础。
#   预注册说明见 docs/PREREG_expand_n30_20261003.md
#
# 纪律：
#   - 落到既有 E14 同目录同命名（results/dispatch_20260921/），保证登记簿 glob 自动纳入
#   - OMP_NUM_THREADS = ceil(24 核 / 6 路) = 4
#   - 跑完必须重跑 scripts/verify_numbers.py 更新 declared 值
# ─────────────────────────────────────────────────────────────────────────────
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."

export PY="C:/Users/Lenovo/AppData/Local/Programs/Python/Python312/python.exe"
export OUT=results/dispatch_20260921
export OMP_NUM_THREADS=4
export MKL_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=4

mkdir -p "$OUT"
LOG="$OUT/run_expand_n30.log"

run_pair() {
  local algo=$1 seed=$2
  "$PY" scripts/run_e14_one.py --algo "$algo" --mode bc_marl   --seed "$seed" --out_dir "$OUT" >> "$LOG" 2>&1
  echo "$(date +%m-%d_%H:%M:%S) DONE $algo bc_marl seed=$seed rc=$?" >> "$LOG"
  "$PY" scripts/run_e14_one.py --algo "$algo" --mode pure_marl --seed "$seed" --out_dir "$OUT" >> "$LOG" 2>&1
  echo "$(date +%m-%d_%H:%M:%S) DONE $algo pure_marl seed=$seed rc=$?" >> "$LOG"
}
export -f run_pair
export PY OUT OMP_NUM_THREADS MKL_NUM_THREADS OPENBLAS_NUM_THREADS LOG

echo "=== E14 expand n=20->n=30 START $(date +%m-%d_%H:%M:%S) algo=iql/vdn/mappo/qmix seeds=120..129 P=6 OMP=4 ===" >> "$LOG"

# 每个 (算法,种子) 作为一个任务，任务内先 bc 后 pure（配对种子时间相邻）
for a in iql vdn mappo qmix; do
  for s in $(seq 120 129); do echo "$a $s"; done
done | xargs -P 6 -I {} bash -c 'set -- {}; run_pair "$1" "$2"'

echo "=== ALL_DONE_EXPAND_N30 $(date +%m-%d_%H:%M:%S) ===" >> "$LOG"

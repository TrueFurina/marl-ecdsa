#!/usr/bin/env bash
# E14 跨算法扩种 n=10 -> n=20（IQL / VDN / MAPPO，新增 seed 110-119）
# 目的：让跨算法四行（NR-63 QMIX / NR-64 IQL / NR-65 VDN / NR-66 MAPPO）全部 n=20/组，
#      把"样本不足、无法判断方向"升级为有检验力的结论（显著与否都如实登记）。
# 纪律：结果直接落 results/dispatch_20260921/（与既有 E14 同目录同命名），
#      登记簿 glob 自动纳入；跑完必须重跑 verify_numbers.py 更新 declared 值。
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PY="C:/Users/Lenovo/AppData/Local/Programs/Python/Python312/python.exe"
export OUT=results/e14_expand_n20_20260930
mkdir -p "$OUT"
LOG="$OUT/run_all.log"

run_pair() {
  local algo=$1 seed=$2
  "$PY" scripts/run_e14_one.py --algo "$algo" --mode bc_marl   --seed "$seed" >> "$LOG" 2>&1
  echo "$(date +%m-%d_%H:%M:%S) DONE $algo bc_marl seed=$seed rc=$?" >> "$LOG"
  "$PY" scripts/run_e14_one.py --algo "$algo" --mode pure_marl --seed "$seed" >> "$LOG" 2>&1
  echo "$(date +%m-%d_%H:%M:%S) DONE $algo pure_marl seed=$seed rc=$?" >> "$LOG"
}
export -f run_pair
export PY OUT LOG

# 每个 (算法,种子) 作为一个任务，任务内先 bc 后 pure，保证配对种子时间相邻（抵消批次漂移）
for a in iql vdn mappo; do
  for s in $(seq 110 119); do echo "$a $s"; done
done | xargs -P 6 -I {} bash -c 'set -- {}; run_pair "$1" "$2"'

echo "ALL_DONE $(date +%m-%d_%H:%M:%S)" >> "$LOG"

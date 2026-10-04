#!/usr/bin/env bash
# moving5 扩种 n=20（种子 100-119，与 moving3 扩种 NR-86 完全同种）
# 目的：替换结论不稳的旧批（env_diversity_20260927 批 Δ=+8.17 与 env_diversity 批 Δ=+1.19 互相矛盾）
# 输出到独立目录，避免与 env_diversity/ 下的混杂种子(7,8,9,14,15,16,17,42,123,456)混淆。
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PY="C:/Users/Lenovo/AppData/Local/Programs/Python/Python312/python.exe"
export OUT=results/env_diversity_moving5_n20
export N_EP=3000
mkdir -p "$OUT"

run_one() {
  local env=$1 mode=$2 seed=$3
  "$PY" scripts/run_env_diversity.py --env "$env" --mode "$mode" --seed "$seed" \
    --n_episodes "$N_EP" --out_dir "$OUT" >> "$OUT/run_all.log" 2>&1
  echo "$(date +%m-%d_%H:%M:%S) DONE $env $mode seed=$seed rc=$?" >> "$OUT/run_all.log"
}
export -f run_one
export N_EP

# 4 路并行；每组内先 bc 后 pure，保证配对种子尽量在时间上相邻（抵消批次漂移）
for s in $(seq 100 119); do echo "$s"; done \
  | xargs -P 4 -I {} bash -c 'run_one moving5 bc_marl {}; run_one moving5 pure_marl {}'

echo "ALL_DONE $(date +%m-%d_%H:%M:%S)" >> "$OUT/run_all.log"

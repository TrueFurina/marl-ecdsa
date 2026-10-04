#!/bin/bash
# 冠军冲刺 E9：受限预算 × 消融（定位"BC 加速协作"的机制来源）
# 问题：BC 在受限预算下加速协作，是哪个组件（security/consensus/incentive）在起作用？
# 设计：500 回合预算下，baseline（全开）vs 关 security/consensus/incentive 三臂，各 30 种子
# 若 ablate-incentive 显著变差 → 激励合约是加速协作的关键
set -u
cd ~/marl-ecdsa-consensus-chain
PY="$HOME/miniconda3/bin/python"
export OMP_NUM_THREADS=2
export MKL_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2
EP=500
OUT=results/champion_20260919
mkdir -p "$OUT"
CMD=/tmp/champion_e9_cmds.txt
: > "$CMD"

gen_e9() {
  for arm in security consensus incentive; do
    for s in $(seq 1001 1030); do
      echo "$PY -X utf8 train.py --mode bc_marl --seed $s --n_episodes $EP --algorithm iql --no-verify-nash --lambda_weight 0.1 --ablate-$arm --save $OUT/e9_b500_ablate_${arm}_seed${s}.json"
    done
  done
}
gen_e9 >> "$CMD"
echo "[$(date)] E9 total commands: $(wc -l < "$CMD")" > "$OUT/e9_batch.log"
cat "$CMD" | xargs -P 48 -I{} bash -c "{}" >> "$OUT/e9_batch.log" 2>&1
echo "[$(date)] E9 ALL DONE" >> "$OUT/e9_batch.log"

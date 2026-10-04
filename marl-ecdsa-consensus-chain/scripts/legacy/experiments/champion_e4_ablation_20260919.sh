#!/bin/bash
# 冠军冲刺 E4：消融扩种子（四臂 × 30 种子 × 3000 回合）
# baseline = E1 的 e1_iql_bc_marl（全开，复用），新增 security/consensus/incentive 三臂
# 统一口径：3000 回合 / λ=0.1 / IQL / 种子 1001-1030
set -u
cd ~/marl-ecdsa-consensus-chain
PY="$HOME/miniconda3/bin/python"
export OMP_NUM_THREADS=2
export MKL_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2
EP=3000
OUT=results/champion_20260919
mkdir -p "$OUT"
CMD=/tmp/champion_e4_cmds.txt
: > "$CMD"

gen_e4() {
  for arm in security consensus incentive; do
    for s in $(seq 1001 1030); do
      echo "$PY -X utf8 train.py --mode bc_marl --seed $s --n_episodes $EP --algorithm iql --no-verify-nash --lambda_weight 0.1 --ablate-$arm --save $OUT/e4_ablate_${arm}_seed${s}.json"
    done
  done
}
gen_e4 >> "$CMD"
echo "[$(date)] E4 total commands: $(wc -l < "$CMD")" > "$OUT/e4_batch.log"
cat "$CMD" | xargs -P 48 -I{} bash -c "{}" >> "$OUT/e4_batch.log" 2>&1
echo "[$(date)] E4 ALL DONE" >> "$OUT/e4_batch.log"

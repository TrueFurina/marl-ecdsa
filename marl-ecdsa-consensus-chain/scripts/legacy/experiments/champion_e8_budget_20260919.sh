#!/bin/bash
# 冠军冲刺 E8：受限训练预算对照（验证"BC 是协作形成加速器"推论）
# 推论：BC 在训练中期加速协作 → 受限预算下 BC 稳态优势应更突出
# 设计：独立训练（非截取），n_episodes ∈ {500, 1000}，bc_marl vs pure_marl，IQL/λ=0.1，30 种子
set -u
cd ~/marl-ecdsa-consensus-chain
PY="$HOME/miniconda3/bin/python"
export OMP_NUM_THREADS=2
export MKL_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2
OUT=results/champion_20260919
mkdir -p "$OUT"
CMD=/tmp/champion_e8_cmds.txt
: > "$CMD"

gen_e8() {
  for ep in 500 1000; do
    for mode in pure_marl bc_marl; do
      for s in $(seq 1001 1030); do
        echo "$PY -X utf8 train.py --mode $mode --seed $s --n_episodes $ep --algorithm iql --no-verify-nash --lambda_weight 0.1 --save $OUT/e8_budget${ep}_${mode}_seed${s}.json"
      done
    done
  done
}
gen_e8 >> "$CMD"
echo "[$(date)] E8 total commands: $(wc -l < "$CMD")" > "$OUT/e8_batch.log"
cat "$CMD" | xargs -P 48 -I{} bash -c "{}" >> "$OUT/e8_batch.log" 2>&1
echo "[$(date)] E8 ALL DONE" >> "$OUT/e8_batch.log"

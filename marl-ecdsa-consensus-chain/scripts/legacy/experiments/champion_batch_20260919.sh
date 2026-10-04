#!/bin/bash
# 冠军冲刺批量训练：E1(三算法x2模式) + E2(lambda扫描) + E3(CARS剂量)
# 统一 3000 回合 / 30 种子(1001-1030) / 真实 torch 路径
set -u
cd ~/marl-ecdsa-consensus-chain
PY="$HOME/miniconda3/bin/python"
export OMP_NUM_THREADS=2
export MKL_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2
EP=3000
OUT=results/champion_20260919
mkdir -p "$OUT"
CMD=/tmp/champion_cmds.txt
: > "$CMD"

gen_e1() {
  for algo in iql vdn qmix; do
    for mode in pure_marl bc_marl; do
      for s in $(seq 1001 1030); do
        echo "$PY -X utf8 train.py --mode $mode --seed $s --n_episodes $EP --algorithm $algo --no-verify-nash --save $OUT/e1_${algo}_${mode}_seed${s}.json"
      done
    done
  done
}
gen_e2() {
  for lam in 0.00 0.05 0.10 0.15; do
    for s in $(seq 1001 1030); do
      echo "$PY -X utf8 train.py --mode bc_marl --seed $s --n_episodes $EP --algorithm iql --no-verify-nash --lambda_weight $lam --save $OUT/e2_lam${lam}_iql_seed${s}.json"
    done
  done
}
gen_e3() {
  for eta in 0.00 0.02 0.05 0.075 0.10 0.15 0.20; do
    for s in $(seq 1001 1030); do
      echo "$PY -X utf8 train.py --mode bc_marl --seed $s --n_episodes $EP --algorithm iql --no-verify-nash --consensus-shaping --shaping-eta $eta --save $OUT/e3_cars${eta}_iql_seed${s}.json"
    done
  done
}
gen_e1 >> "$CMD"
gen_e2 >> "$CMD"
gen_e3 >> "$CMD"
echo "[$(date)] total commands: $(wc -l < "$CMD")" > "$OUT/batch.log"
cat "$CMD" | xargs -P 48 -I{} bash -c "{}" >> "$OUT/batch.log" 2>&1
echo "[$(date)] ALL DONE" >> "$OUT/batch.log"

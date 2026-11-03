#!/bin/bash
cd ~/marl-ecdsa-consensus-chain
source ~/miniconda3/etc/profile.d/conda.sh
conda activate marl
mkdir -p results/vdn_ab
for seed in 42 100 200 300 400; do
  for cred in "" "--credibility"; do
    if [ -z "$cred" ]; then tag="base"; else tag="cred"; fi
    out="results/vdn_ab/${tag}_s${seed}.json"
    if [ ! -f "$out" ]; then
      echo "running $tag s$seed..."
      python -X utf8 train_delivery_vdn.py --seed $seed --episodes 10000 --lam 1.0 --out $out $cred
    fi
  done
done
echo ALL_DONE

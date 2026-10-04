#!/bin/bash
# 深度测试 bash 编排器 (后台兼容版, 断点续跑)
PYTHON="python"
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mkdir -p results/ablation results/convergence_3000 results/hp_sweep

run() {
  tag="$1"; save="$2"; shift 2
  if [ -f "$save" ]; then echo "[SKIP] $tag"; return; fi
  echo "[START $(date +%H:%M:%S)] $tag"
  "$PYTHON" train.py "$@" --save "$save" >>results/deep_tests.log 2>&1
  if [ $? -eq 0 ]; then echo "[DONE] $tag"; else echo "[FAIL] $tag"; fi
}

echo "=== Tier1: Scalability (5/8 agents) ==="
for n in 5 8; do
  for mode in pure_marl bc_marl; do
    for seed in 42 123 456; do
      run "scal_${n}_${mode}_s${seed}" "results/scalability_test/agents_${n}_${mode}_seed${seed}.json" \
        --mode $mode --n_agents $n --n_landmarks $n --seed $seed --n_episodes 500
    done
  done
done

echo "=== Tier2: Ablation (bc_marl, 3 agents) ==="
for seed in 42 123 456; do
  run "abl_baseline_s${seed}" "results/ablation/baseline_seed${seed}.json" \
    --mode bc_marl --n_agents 3 --n_landmarks 3 --seed $seed --n_episodes 500
done
for mod in security consensus incentive; do
  for seed in 42 123 456; do
    flag="--ablate-$mod"
    run "abl_${mod}_s${seed}" "results/ablation/${mod}_seed${seed}.json" \
      --mode bc_marl --n_agents 3 --n_landmarks 3 --seed $seed --n_episodes 500 $flag
  done
done

echo "=== Tier3: Convergence 3000ep (3 agents) ==="
for mode in pure_marl bc_marl; do
  for seed in 42 123 456; do
    run "conv3000_${mode}_s${seed}" "results/convergence_3000/${mode}_seed${seed}.json" \
      --mode $mode --n_agents 3 --n_landmarks 3 --seed $seed --n_episodes 3000
  done
done

echo "=== Tier4: Hyperparam sweep (bc_marl, 3 agents) ==="
run "hp_g0.9_lr1e-3_s42" "results/hp_sweep/g0.9_lr1e-3_seed42.json" --mode bc_marl --n_agents 3 --n_landmarks 3 --seed 42 --n_episodes 500 --gamma 0.9 --lr 1e-3
run "hp_g0.9_lr1e-3_s123" "results/hp_sweep/g0.9_lr1e-3_seed123.json" --mode bc_marl --n_agents 3 --n_landmarks 3 --seed 123 --n_episodes 500 --gamma 0.9 --lr 1e-3
run "hp_g0.9_lr1e-3_s456" "results/hp_sweep/g0.9_lr1e-3_seed456.json" --mode bc_marl --n_agents 3 --n_landmarks 3 --seed 456 --n_episodes 500 --gamma 0.9 --lr 1e-3
run "hp_g0.8_lr5e-4_s42" "results/hp_sweep/g0.8_lr5e-4_seed42.json" --mode bc_marl --n_agents 3 --n_landmarks 3 --seed 42 --n_episodes 500 --gamma 0.8 --lr 5e-4
run "hp_g0.8_lr5e-4_s123" "results/hp_sweep/g0.8_lr5e-4_seed123.json" --mode bc_marl --n_agents 3 --n_landmarks 3 --seed 123 --n_episodes 500 --gamma 0.8 --lr 5e-4
run "hp_g0.8_lr5e-4_s456" "results/hp_sweep/g0.8_lr5e-4_seed456.json" --mode bc_marl --n_agents 3 --n_landmarks 3 --seed 456 --n_episodes 500 --gamma 0.8 --lr 5e-4
run "hp_g0.9_lr5e-4_s42" "results/hp_sweep/g0.9_lr5e-4_seed42.json" --mode bc_marl --n_agents 3 --n_landmarks 3 --seed 42 --n_episodes 500 --gamma 0.9 --lr 5e-4
run "hp_g0.9_lr5e-4_s123" "results/hp_sweep/g0.9_lr5e-4_seed123.json" --mode bc_marl --n_agents 3 --n_landmarks 3 --seed 123 --n_episodes 500 --gamma 0.9 --lr 5e-4
run "hp_g0.9_lr5e-4_s456" "results/hp_sweep/g0.9_lr5e-4_seed456.json" --mode bc_marl --n_agents 3 --n_landmarks 3 --seed 456 --n_episodes 500 --gamma 0.9 --lr 5e-4

echo "=== ALL DEEP TESTS COMPLETE ==="

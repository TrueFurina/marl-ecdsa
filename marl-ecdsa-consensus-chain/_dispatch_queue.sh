#!/usr/bin/env bash
# =============================================================================
# E13 / E14 派单队列（服务器端，tmux 托管）
#   E13  自私攻击强度对照：random(噪声) vs greedy(理性) × {0%,20%,50%} × 10 seed
#   E14  第四算法正式对比：iql/vdn/qmix/mappo × 3000ep × 10 seed
#
# 设计要点（都是踩过坑之后的）：
#   1) 顺序执行 —— 结果文件写死在 CWD，并行会互相覆盖；GPU 单卡也不该自己抢自己
#   2) 可断点续跑 —— 目标文件已存在则 SKIP（重跑只需重启本脚本）
#   3) 每次运行产物按 tag 归档到 dispatch/，并追加一行 STATUS.tsv（tag/exit/耗时）
#   4) --save 指定绝对路径，避免 train.py 覆盖根目录的 training_results.json
#   5) timeout 兜底：单任务超 1 小时判死，不让队列卡住
# =============================================================================
set -u

REPO="$HOME/marl-ecdsa-consensus-chain"
PY="$HOME/miniconda3/envs/gomarl/bin/python"     # cu128，Blackwell 唯一实测可算的环境
D="$REPO/dispatch"
LOGS="$D/logs"
STATUS="$D/STATUS.tsv"

mkdir -p "$LOGS"
[ -f "$STATUS" ] || printf 'tag\texit\telapsed_s\n' > "$STATUS"
cd "$REPO" || exit 1

echo "[queue] start $(date '+%F %T')  py=$PY"

run_one() {
  local tag="$1"; shift
  local out="$D/$tag.json"
  if [ -f "$out" ]; then
    echo "[skip] $tag (already done)"; return 0
  fi
  local t0 t1 rc
  t0=$(date +%s)
  timeout 3600 "$@" > "$LOGS/$tag.log" 2>&1
  rc=$?
  t1=$(date +%s)

  if [ ! -f "$out" ]; then
    # 未走 --save 的脚本把结果写在 CWD，归档之
    if [ -f experiment_results.json ]; then cp -f experiment_results.json "$out"
    elif [ -f training_results.json ]; then cp -f training_results.json "$out"
    fi
  fi
  rm -f experiment_results.json training_results.json

  printf '%s\t%s\t%s\n' "$tag" "$rc" "$((t1 - t0))" >> "$STATUS"
  echo "[done] $tag exit=$rc $((t1 - t0))s"
}

# ---------------------------- E13：自私攻击强度 ----------------------------
for s in 100 101 102 103 104 105 106 107 108 109; do
  run_one "e13_expb_seed$s" \
    "$PY" -u experiments/run_experiment.py --exp b --n_episodes 500 --seed "$s"
done

# ---------------------------- E14：四算法正式对比 --------------------------
for a in iql vdn qmix mappo; do
  for s in 100 101 102 103 104 105 106 107 108 109; do
    run_one "e14_${a}_seed$s" \
      "$PY" -u train.py --algorithm "$a" --n_episodes 3000 --seed "$s" \
      --save "$D/e14_${a}_seed$s.json"
  done
done

echo "[queue] ALL DONE $(date '+%F %T')"

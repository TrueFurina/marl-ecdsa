#!/usr/bin/env bash
# 任务 A｜环境多样性扩展 —— 全量批量启动器（服务器端）
# 在仓库根目录执行： nohup bash scripts/run_env_div_batch.sh >/dev/null 2>&1 &
# 并行策略：4 个 (env,mode) 组并行，每组内 10 种子以 xargs -P 6 并发。
# 沿用项目既有惯例（E4 即用 nohup + xargs -P 后台跑），并配合 [r]un_env_diversity 轮询监控。
set -u
# 路径可由环境变量覆盖：MARL_REPO_DIR=仓库根（默认脚本上一级），MARL_PY=解释器（默认 PATH 中 python）
REPO_DIR="${MARL_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$REPO_DIR"
export PY="${MARL_PY:-python}"
export OUT=results/env_diversity_20260927
mkdir -p "$OUT"

run_one() {
  local env=$1 mode=$2 seed=$3
  "$PY" scripts/run_env_diversity.py --env "$env" --mode "$mode" --seed "$seed" \
    --n_episodes 3000 --no-verify-nash >> "$OUT/run_${env}_${mode}.log" 2>&1
  echo "$(date +%H:%M:%S) DONE env=$env mode=$mode seed=$seed rc=$?" >> "$OUT/run_${env}_${mode}.log"
}
export -f run_one

SEEDS="42 43 44 45 46 47 48 49 50 51"
for env in moving3 moving5; do
  for mode in bc_marl pure_marl; do
    ( for s in $SEEDS; do echo "$s"; done | xargs -P 6 -I {} bash -c "run_one $env $mode {}" ) &
  done
done
wait
echo "ALL_DONE $(date)" >> "$OUT/run_all.log"

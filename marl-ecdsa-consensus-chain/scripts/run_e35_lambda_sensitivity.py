# -*- coding: utf-8 -*-
"""E35 λ × 三口径敏感性（预注册实验）
=====================================
目的：检验主证据（BC vs PURE 的 env_reward / 合作率增益）是否**只在 λ=0.1 成立**。
      评审最常问的参数质疑：「你是不是只挑了好看的 λ？」

设计（预注册 docs/PREREG_e35_lambda_sensitivity.md）：
  - 环境 w3x3（3 agent / 3 landmark，与主证据 NR-129 同环境）
  - 算法 IQL（与主证据同算法）
  - 预算 1000ep（与 E18/E20 同预算，非主证据的 3000ep —— 口径必须标注）
  - λ ∈ {0.1, 0.3, 0.5, 0.7}，n=20/档/组，seeds 1001-1020（与 E18/E20 同种子区间）
  - arms: bc_marl × 4 档 λ + pure_marl × 1 组（pure 无 BC 激励，λ 不起作用，
    故只跑一组；仍按 λ=0.1 标记以与 E18 对称）
  - 三口径（末50 / 全程 / 合作率）全部从同一份数据计算

总场次：4×20 + 20 = 100 场

用法（服务器）：
    ~/venv_torch/bin/python run_e35_lambda_sensitivity.py <shard> <nshard>
"""
import os, sys, json, time, itertools
from pathlib import Path

ROOT = Path("/home/user/marl-ecdsa-consensus-chain")
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)

SEEDS    = list(range(1001, 1021))     # n=20
CFGS     = {"w3x3": (3, 3)}            # 与主证据同环境
LAMBDAS  = [0.1, 0.3, 0.5, 0.7]        # 4 档
N_EP     = 1000
OUT      = ROOT / "results" / "e35_lambda_sensitivity"
OUT.mkdir(parents=True, exist_ok=True)

shard  = int(sys.argv[1]) if len(sys.argv) > 1 else 0
nshard = int(sys.argv[2]) if len(sys.argv) > 2 else 1

from train import TrainingConfig, MARLBlockchainTrainer

# 作业清单：bc_marl × 4λ + pure_marl × 1(λ=0.1 标记)
jobs = []
for lam in LAMBDAS:
    for seed in SEEDS:
        jobs.append(("w3x3", "bc_marl", lam, seed))
for seed in SEEDS:
    jobs.append(("w3x3", "pure_marl", 0.1, seed))
jobs = jobs[shard::nshard]

print(f"[E35] shard {shard}/{nshard} | 本片 {len(jobs)} 场", flush=True)

for cfg, arm, lam, seed in jobs:
    na, nl = CFGS[cfg]
    lam_s = str(lam).replace(".", "p")   # 禁用 :.1f（两位小数 λ 会退化致同名覆盖丢数据）
    tag = f"e35_{cfg}_seed{seed}_{arm}_lam{lam_s}"
    fp = OUT / f"{tag}.json"
    if fp.exists():
        print(f"[skip] {tag}", flush=True); continue
    t0 = time.time()
    c = TrainingConfig(n_agents=na, n_landmarks=nl, n_episodes=N_EP,
                       mode=arm, seed=seed, lambda_weight=lam)
    s = MARLBlockchainTrainer(c).train().summary()
    s["_e35"] = {"cfg": cfg, "n_agents": na, "n_landmarks": nl, "mode": arm,
                 "lambda": lam, "seed": seed, "n_episodes": N_EP,
                 "elapsed_sec": round(time.time() - t0, 1)}
    fp.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[ok] {tag} env50={s.get('avg_env_reward_last_50')} "
          f"envfull={s.get('avg_env_reward')} coop={s.get('avg_cooperation_rate')} "
          f"{time.time()-t0:.0f}s", flush=True)

print(f"[shard {shard}/{nshard}] DONE", flush=True)

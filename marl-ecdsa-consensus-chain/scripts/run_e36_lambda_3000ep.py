# -*- coding: utf-8 -*-
"""E36 λ × 三口径敏感性 @ 3000ep（预注册实验）
=============================================
动机：E35（1000ep）发现 **λ=0.1 三口径全不显著**，而 λ=0.3/0.5/0.7 九项全过
      Bonferroni。但主证据（NR-129）是 **3000ep / λ=0.1 / p=0.0034 显著**。
      → 必须检验：**在主证据同预算（3000ep）下，λ 敏感性是否同样成立？**
       若 3000ep 下 λ=0.1 显著而更高 λ 也显著 → 「λ=0.1 非挑值，且增益随 λ 增强」
       若 3000ep 下 λ=0.1 是唯一显著档 → 「增益集中在该设定，需说明依据」
       若 3000ep 下 λ=0.1 也不显著 → 与 NR-129 冲突，必须停下来核查（不应发生）

设计（预注册 docs/PREREG_e36_lambda_3000ep.md，执行中不可更改）：
  - 环境 w3x3 / 算法 IQL / **预算 3000ep**（与主证据 NR-129 同预算）
  - λ ∈ {0.1, 0.3, 0.5, 0.7}，n=20/档/组
  - **seeds 3001-3020**（全新独立区间，不与 convergence_3000/e31_main_n101 的
    42/123/456/2001-2030 混淆；pure 臂同批新种子，保证配对）
  - 三口径全部从同一份数据计算

总场次：4λ×20 + 20 = 100 场

用法（服务器）：
    ~/venv_torch/bin/python run_e36_lambda_3000ep.py <shard> <nshard>
"""
import os, sys, json, time, itertools
from pathlib import Path

ROOT = Path("/home/user/marl-ecdsa-consensus-chain")
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)

SEEDS   = list(range(3001, 3021))     # n=20，全新独立区间
CFGS    = {"w3x3": (3, 3)}
LAMBDAS = [0.1, 0.3, 0.5, 0.7]
N_EP    = 3000                         # 与主证据同预算
OUT     = ROOT / "results" / "e36_lambda_3000ep"
OUT.mkdir(parents=True, exist_ok=True)

shard  = int(sys.argv[1]) if len(sys.argv) > 1 else 0
nshard = int(sys.argv[2]) if len(sys.argv) > 2 else 1

from train import TrainingConfig, MARLBlockchainTrainer

jobs = []
for lam in LAMBDAS:
    for seed in SEEDS:
        jobs.append(("w3x3", "bc_marl", lam, seed))
for seed in SEEDS:
    jobs.append(("w3x3", "pure_marl", 0.1, seed))
jobs = jobs[shard::nshard]

print(f"[E36] shard {shard}/{nshard} | 本片 {len(jobs)} 场 | 3000ep", flush=True)

for cfg, arm, lam, seed in jobs:
    na, nl = CFGS[cfg]
    lam_s = str(lam).replace(".", "p")   # 禁用 :.1f（两位小数 λ 会退化致同名覆盖丢数据）
    tag = f"e36_{cfg}_seed{seed}_{arm}_lam{lam_s}"
    fp = OUT / f"{tag}.json"
    if fp.exists():
        print(f"[skip] {tag}", flush=True); continue
    t0 = time.time()
    c = TrainingConfig(n_agents=na, n_landmarks=nl, n_episodes=N_EP,
                       mode=arm, seed=seed, lambda_weight=lam)
    s = MARLBlockchainTrainer(c).train().summary()
    s["_e36"] = {"cfg": cfg, "n_agents": na, "n_landmarks": nl, "mode": arm,
                 "lambda": lam, "seed": seed, "n_episodes": N_EP,
                 "elapsed_sec": round(time.time() - t0, 1)}
    fp.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[ok] {tag} env50={s.get('avg_env_reward_last_50')} "
          f"envfull={s.get('avg_env_reward')} coop={s.get('avg_cooperation_rate')} "
          f"{time.time()-t0:.0f}s", flush=True)

print(f"[shard {shard}/{nshard}] DONE", flush=True)

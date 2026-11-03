"""E40 λ 在线自适应深度对照实验（预注册 docs/PREREG_e40_adaptive_lambda.md）

五臂 @ 3000ep / w3x3 / IQL / n=20 per arm / seeds 3101-3120（全新独立区间）：
  A  static λ=0.1   (adaptive_lambda=False，真静态基线——历史实验从未有此臂)
  B  adaptive base=0.1 β=2.0（当前代码默认状态 ≈ 历史实验状态）
  C  adaptive base=0.1 β=5.0（灵敏版，sigmoid 陡度 ×2.5）★核心增益假设
  E  static λ=0.15  (上界静态对照)
  F  pure_marl      (主效应同批对照)

用法（服务器 8 分片）:
    OMP_NUM_THREADS=16 ~/venv_torch/bin/python scripts/run_e40_adaptive_lambda.py <shard> <nshard>

判定标准见预注册（Bonferroni α/4，三口径并列，诚实条款）。
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from train import TrainingConfig, MARLBlockchainTrainer  # noqa: E402

N_EP = 3000
SEEDS = list(range(3101, 3121))          # n=20，全新独立区间（不与 1001-1020/3001-3060/2001-2030 重叠）
OUT = ROOT / "results" / "e40_adaptive_lambda"

# (tag, mode, lambda_weight, adaptive_lambda, adaptive_beta)
ARMS = [
    ("A_static01",  "bc_marl", 0.1,  False, 2.0),
    ("B_adaptDef",  "bc_marl", 0.1,  True,  2.0),
    ("C_adaptB5",   "bc_marl", 0.1,  True,  5.0),
    ("E_static015", "bc_marl", 0.15, False, 2.0),
    ("F_pure",      "pure_marl", 0.0, True, 2.0),
]


def main(shard: int, nshard: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [(arm, seed) for arm in ARMS for seed in SEEDS]
    mine = [j for i, j in enumerate(jobs) if i % nshard == shard]
    print(f"[E40] shard {shard}/{nshard}: {len(mine)}/{len(jobs)} 场", flush=True)
    for arm, seed in mine:
        tag, mode, lam, adaptive, beta = arm
        tag_f = f"e40_{tag}_seed{seed}"
        fp = OUT / f"{tag_f}.json"
        if fp.exists():
            print(f"[skip] {tag_f}", flush=True)
            continue
        t0 = time.time()
        c = TrainingConfig(
            n_agents=4, n_landmarks=2, n_episodes=N_EP,
            mode=mode, seed=seed, lambda_weight=lam,
            adaptive_lambda=adaptive, adaptive_beta=beta,
        )
        s = MARLBlockchainTrainer(c).train().summary()
        s["_e40"] = {"arm": tag, "mode": mode, "lambda_base": lam,
                     "adaptive": adaptive, "beta": beta, "seed": seed,
                     "n_episodes": N_EP, "elapsed_sec": round(time.time() - t0, 1)}
        fp.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[ok] {tag_f} env50={s.get('avg_env_reward_last_50')} "
              f"λmean={s.get('lambda_mean')} elapsed={s['_e40']['elapsed_sec']}s", flush=True)
    print(f"[E40] DONE shard {shard}", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]))

#!/usr/bin/env python3
"""修正版公平对比训练 — V3.7
核心修复：同时记录 env_rewards（纯环境奖励）和 episode_rewards（含BC激励总奖励）
参数：lambda=0.1, seed=42, 3000 episodes
公平对比：pure_marl env_rewards vs bc_marl env_rewards（同一基准线）
"""


# ===== 自动注入: 仓库根路径 (legacy 移动兼容) =====
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = str(_Path(__file__).resolve().parent.parent.parent.parent)
if _REPO_ROOT not in _sys.path:
    _sys.path.insert(0, _REPO_ROOT)
# ===== 自动注入结束 =====

import sys
import json
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from train import TrainingConfig, MARLBlockchainTrainer

BASE_DIR = _REPO_ROOT
OUTPUT_DIR = os.path.join(BASE_DIR, "results", "fixed_comparison")
os.makedirs(OUTPUT_DIR, exist_ok=True)

COMMON_ARGS = {
    "n_agents": 3,
    "n_landmarks": 3,
    "n_episodes": 3000,
    "max_steps": 25,
    "hidden_dim": 128,
    "lr": 0.001,
    "gamma": 0.8,
    "batch_size": 64,
    "epsilon_decay": 5000,
    "seed": 42,
    "log_interval": 200,
    "save_interval": 500,
    "use_p2p": False,
}

def run_pure_marl():
    """纯MARL基准：无区块链"""
    print("\n" + "=" * 60)
    print("PURE MARL TRAINING (seed=42, 3000eps)")
    print("=" * 60)
    config = TrainingConfig(**COMMON_ARGS, mode="pure_marl", lambda_weight=0.0, selfish_ratio=0.0)
    trainer = MARLBlockchainTrainer(config)
    stats = trainer.train()
    out = os.path.join(OUTPUT_DIR, "pure_marl_seed42_lambda0.0.json")
    trainer.export_results(out)
    print(f"Saved: {out}")
    env_avg = sum(stats.env_rewards) / len(stats.env_rewards) if stats.env_rewards else 0
    print(f"Pure env_reward avg: {env_avg:.2f}")
    return stats

def run_bc_marl():
    """BC-MARL：lambda=0.1"""
    print("\n" + "=" * 60)
    print("BC-MARL TRAINING (seed=42, lambda=0.1, 3000eps)")
    print("=" * 60)
    config = TrainingConfig(**COMMON_ARGS, mode="bc_marl", lambda_weight=0.1, selfish_ratio=0.0)
    trainer = MARLBlockchainTrainer(config)
    stats = trainer.train()
    out = os.path.join(OUTPUT_DIR, "bc_marl_seed42_lambda0.1.json")
    trainer.export_results(out)
    print(f"Saved: {out}")
    env_avg = sum(stats.env_rewards) / len(stats.env_rewards) if stats.env_rewards else 0
    total_avg = sum(stats.episode_rewards) / len(stats.episode_rewards)
    print(f"BC env_reward avg: {env_avg:.2f}")
    print(f"BC total_reward avg: {total_avg:.2f}")
    return stats

if __name__ == "__main__":
    t0 = time.time()
    pure_stats = run_pure_marl()
    bc_stats = run_bc_marl()
    elapsed = time.time() - t0

    # 公平对比（基于 env_rewards）
    if pure_stats.env_rewards and bc_stats.env_rewards:
        pure_env_avg = sum(pure_stats.env_rewards) / len(pure_stats.env_rewards)
        bc_env_avg = sum(bc_stats.env_rewards) / len(bc_stats.env_rewards)
        pure_env_l50 = sum(pure_stats.env_rewards[-50:]) / 50
        bc_env_l50 = sum(bc_stats.env_rewards[-50:]) / 50

        print("\n" + "=" * 60)
        print("FAIR COMPARISON (env_rewards only, no BC bonus)")
        print("=" * 60)
        print(f"Pure MARL:  env_avg={pure_env_avg:.2f}, env_last50={pure_env_l50:.2f}")
        print(f"BC-MARL:    env_avg={bc_env_avg:.2f}, env_last50={bc_env_l50:.2f}")
        improvement = (abs(pure_env_avg) - abs(bc_env_avg)) / abs(pure_env_avg) * 100
        print(f"BC Improvement (fair): {improvement:.1f}%")

        # 保存汇总报告
        report = {
            "description": "V3.7 fixed comparison: env_rewards used for fair BC vs Pure comparison",
            "training_time_sec": round(elapsed, 1),
            "pure_marl": {
                "env_avg": round(pure_env_avg, 2),
                "env_last50": round(pure_env_l50, 2),
                "total_avg": round(sum(pure_stats.episode_rewards) / len(pure_stats.episode_rewards), 2),
            },
            "bc_marl": {
                "env_avg": round(bc_env_avg, 2),
                "env_last50": round(bc_env_l50, 2),
                "total_avg": round(sum(bc_stats.episode_rewards) / len(bc_stats.episode_rewards), 2),
            },
            "bc_improvement_pct": round(improvement, 1),
            "note": "env_rewards = pure environment reward (no BC bonus), fair comparison baseline"
        }
        report_path = os.path.join(OUTPUT_DIR, "fair_comparison_report.json")
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\nReport saved: {report_path}")

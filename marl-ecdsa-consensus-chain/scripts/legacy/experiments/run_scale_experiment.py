"""
多智能体规模实验脚本 — 验证 BC-MARL 在不同智能体数量下的可扩展性

运行方式:
    python run_scale_experiment.py              # 默认：3/5/10 agents
    python run_scale_experiment.py --agents 3 5 10 20  # 自定义
    python run_scale_experiment.py --episodes 200 --seeds 3
"""

# ===== 自动注入: 仓库根路径 (legacy 移动兼容) =====
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = str(_Path(__file__).resolve().parent.parent.parent.parent)
if _REPO_ROOT not in _sys.path:
    _sys.path.insert(0, _REPO_ROOT)
# ===== 自动注入结束 =====

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = _Path(_REPO_ROOT)
sys.path.insert(0, str(ROOT))

from train import TrainingConfig, MARLBlockchainTrainer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('scale_exp')


def run_single(
    n_agents: int,
    n_episodes: int,
    mode: str,
    seed: int,
    lambda_weight: float,
) -> dict:
    """运行单次训练，返回摘要统计"""
    config = TrainingConfig(
        n_agents=n_agents,
        n_landmarks=n_agents,  # 路标数 = 智能体数
        n_episodes=n_episodes,
        mode=mode,
        lambda_weight=lambda_weight,
        selfish_ratio=0.0,
        seed=seed,
    )
    trainer = MARLBlockchainTrainer(config)
    stats = trainer.train()
    summary = stats.summary()
    summary['seed'] = seed
    summary['n_agents'] = n_agents
    summary['mode'] = mode
    return summary


def _collect_results(agents_list, n_episodes, n_seeds, lambda_weight, seed_list):
    """收集所有实验配置的结果"""
    results = {}
    for n_agents in agents_list:
        logger.info(f"{'='*60}\n智能体数: {n_agents}\n{'='*60}")
        for mode in ['pure_marl', 'bc_marl']:
            lam = lambda_weight if mode == 'bc_marl' else 0.0
            env_rewards, total_rewards, coop_rates, times = [], [], [], []
            for seed_idx, seed in enumerate(seed_list[:n_seeds]):
                logger.info(f"  [{mode}] seed={seed} ({seed_idx+1}/{n_seeds})")
                t0 = time.time()
                summary = run_single(n_agents, n_episodes, mode, seed, lam)
                elapsed = time.time() - t0
                env_rewards.append(summary['avg_env_reward'])
                total_rewards.append(summary['avg_reward'])
                coop_rates.append(summary['avg_cooperation_rate'])
                times.append(elapsed)
                logger.info(f"    env_reward={summary['avg_env_reward']:.2f}, coop={summary['avg_cooperation_rate']:.2%}, 耗时={elapsed:.1f}s")
            key = f"{mode}_n{n_agents}"
            results[key] = {
                'n_agents': n_agents, 'mode': mode, 'n_seeds': n_seeds, 'n_episodes': n_episodes,
                'env_reward_mean': float(np.mean(env_rewards)), 'env_reward_std': float(np.std(env_rewards)),
                'total_reward_mean': float(np.mean(total_rewards)), 'total_reward_std': float(np.std(total_rewards)),
                'coop_rate_mean': float(np.mean(coop_rates)), 'coop_rate_std': float(np.std(coop_rates)),
                'avg_time_sec': float(np.mean(times)),
                'all_env_rewards': env_rewards, 'all_coop_rates': coop_rates,
            }
    return results


def _compute_bc_improvements(results, agents_list):
    """计算 BC 提升"""
    for n_agents in agents_list:
        pure_key, bc_key = f"pure_marl_n{n_agents}", f"bc_marl_n{n_agents}"
        if pure_key in results and bc_key in results:
            p, b = results[pure_key], results[bc_key]
            imp = (b['env_reward_mean'] - p['env_reward_mean']) / max(0.001, abs(p['env_reward_mean'])) * 100
            results[f"bc_improvement_n{n_agents}"] = {
                'n_agents': n_agents, 'improvement_pct': round(imp, 2),
                'pure_env_reward': round(p['env_reward_mean'], 2), 'bc_env_reward': round(b['env_reward_mean'], 2),
                'pure_coop': round(p['coop_rate_mean'], 4), 'bc_coop': round(b['coop_rate_mean'], 4),
            }


def _print_report(results, agents_list):
    """打印报告"""
    print("\n" + "=" * 60)
    print("多智能体规模实验报告")
    print("=" * 60)
    print(f"{'智能体数':>8} | {'模式':>10} | {'env_reward':>10} | {'合作率':>8} | {'BC提升':>8} | {'耗时':>8}")
    print("-" * 60)
    for n_agents in agents_list:
        for mode in ['pure_marl', 'bc_marl']:
            key = f"{mode}_n{n_agents}"
            if key in results:
                r = results[key]
                impr = f"{results[f'bc_improvement_n{n_agents}']['improvement_pct']:+.1f}%" if f"bc_improvement_n{n_agents}" in results else ""
                if mode == 'pure_marl':
                    print(f"{n_agents:>8} | {mode:>10} | {r['env_reward_mean']:.1f}±{r['env_reward_std']:.1f} | {r['coop_rate_mean']:.1%} | {impr:>8} | {r['avg_time_sec']:.0f}s")
                else:
                    print(f"{'':>8} | {mode:>10} | {r['env_reward_mean']:.1f}±{r['env_reward_std']:.1f} | {r['coop_rate_mean']:.1%} | {'':>8} | {r['avg_time_sec']:.0f}s")
        print("-" * 60)


def run_scale_experiment(args):
    """运行多智能体规模实验"""
    results = _collect_results(args.agents, args.episodes, args.seeds, args.lambda_weight, args.seed_list)
    _compute_bc_improvements(results, args.agents)
    output_path = ROOT / args.output
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info(f"结果已保存至: {output_path}")
    _print_report(results, args.agents)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='多智能体规模实验')
    parser.add_argument('--agents', type=int, nargs='+', default=[3, 5, 10],
                        help='智能体数量列表')
    parser.add_argument('--episodes', type=int, default=200,
                        help='每种子训练回合数')
    parser.add_argument('--seeds', type=int, default=3,
                        help='独立随机种子数')
    parser.add_argument('--seed-list', type=int, nargs='+',
                        default=[42, 123, 456],
                        help='种子列表')
    parser.add_argument('--lambda-weight', type=float, default=0.1,
                        help='区块链激励权重')
    parser.add_argument('--output', type=str, default='results/scale_experiment.json',
                        help='输出文件路径')
    args = parser.parse_args()

    run_scale_experiment(args)
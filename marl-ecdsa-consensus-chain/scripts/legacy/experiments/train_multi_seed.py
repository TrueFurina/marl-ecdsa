"""
多种子训练脚本（竞赛级）
3种子 × 3模式 × 3000回合 = 9轮训练
输出：每种子独立结果 + 合并结果（均值±标准差 + 95%置信区间）

用法：python train_multi_seed.py
"""

# ===== 自动注入: 仓库根路径 (legacy 移动兼容) =====
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = str(_Path(__file__).resolve().parent.parent.parent.parent)
if _REPO_ROOT not in _sys.path:
    _sys.path.insert(0, _REPO_ROOT)
# ===== 自动注入结束 =====

import json
import logging
import sys
import time
import numpy as np
from pathlib import Path
from datetime import datetime
from scipy.stats import t as t_dist

sys.path.insert(0, str(Path(__file__).parent))

from train import TrainingConfig, MARLBlockchainTrainer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('multi_seed')

BASE_DIR = _Path(_REPO_ROOT)
RESULTS_DIR = BASE_DIR / 'results'
RESULTS_DIR.mkdir(exist_ok=True)

# =============================================================================
# 训练配置
# =============================================================================
SEEDS = [42, 123, 456]
MODES = ['pure_marl', 'bc_marl', 'selfish']
N_EPISODES = 3000

# 模式特定配置
MODE_CONFIGS = {
    'pure_marl': {'lambda_weight': 0.0, 'selfish_ratio': 0.0},
    'bc_marl': {'lambda_weight': 0.1, 'selfish_ratio': 0.0},
    'selfish': {'lambda_weight': 0.1, 'selfish_ratio': 0.3},
}


def train_one_seed(mode: str, seed: int, n_episodes: int):
    """训练单个种子的单个模式"""
    mc = MODE_CONFIGS[mode]
    config = TrainingConfig(
        n_agents=3,
        n_landmarks=3,
        n_episodes=n_episodes,
        max_steps=25,
        hidden_dim=128,
        lr=1e-3,
        gamma=0.8,
        batch_size=64,
        lambda_weight=mc['lambda_weight'],
        selfish_ratio=mc['selfish_ratio'],
        mode=mode,
        seed=seed,
        log_interval=200,
    )

    logger.info(f"[{mode}] 种子={seed} 开始训练（{n_episodes}回合）")
    trainer = MARLBlockchainTrainer(config)
    stats = trainer.train()

    output_path = RESULTS_DIR / f'training_results_{mode}_seed{seed}.json'
    trainer.export_results(str(output_path))
    trainer.cleanup()
    logger.info(f"[{mode}] 种子={seed} 完成 → {output_path}")

    return str(output_path)


def combine_results(mode: str, seed_results: list):
    """
    合并多个种子的结果，生成均值±标准差 + 95%置信区间
    """
    n_seeds = len(seed_results)
    if n_seeds == 0:
        return None

    # 读取所有种子数据
    all_data = []
    for path in seed_results:
        with open(path, 'r', encoding='utf-8') as f:
            all_data.append(json.load(f))

    # 确定最小回合数（对齐）
    min_eps = min(len(d['episode_rewards']) for d in all_data)
    n_episodes = min_eps

    # ── episode_rewards ──
    reward_matrix = np.array([d['episode_rewards'][:n_episodes] for d in all_data])  # (n_seeds, n_eps)
    reward_mean = reward_matrix.mean(axis=0)
    reward_std = reward_matrix.std(axis=0, ddof=1)  # sample std
    reward_se = reward_std / np.sqrt(n_seeds)        # standard error
    # 95% CI = mean ± t(0.975, df=n_seeds-1) * SE（小样本用t-分布，非正态近似）
    t_crit = t_dist.ppf(0.975, df=n_seeds - 1) if n_seeds > 1 else 1.96
    ci = t_crit * reward_se

    # ── cooperation_rates ──
    coop_matrix = np.array([d['cooperation_rates'][:n_episodes] for d in all_data])
    coop_mean = coop_matrix.mean(axis=0)
    coop_std = coop_matrix.std(axis=0, ddof=1)

    # ── 汇总指标 ──
    summaries = [d['summary'] for d in all_data]
    avg_rewards = [s['avg_reward'] for s in summaries]
    avg_rewards_last50 = [s['avg_reward_last_50'] for s in summaries]
    avg_coops = [s['avg_cooperation_rate'] for s in summaries]
    elapsed_times = [s['elapsed_time'] for s in summaries]

    def _mean_std(values):
        arr = np.array(values)
        return float(arr.mean()), float(arr.std(ddof=1))

    avg_r, std_r = _mean_std(avg_rewards)
    last50_r, std_last50 = _mean_std(avg_rewards_last50)
    avg_c, std_c = _mean_std(avg_coops)

    combined = {
        'mode': mode,
        'n_seeds': n_seeds,
        'seeds': SEEDS[:n_seeds],
        'n_episodes': n_episodes,
        'config': all_data[0].get('config', {}),
        'summary': {
            'total_episodes': n_episodes,
            'avg_reward': avg_r,
            'avg_reward_std': std_r,
            'avg_reward_ci95': float(t_crit * std_r / np.sqrt(n_seeds)),
            'avg_reward_last_50': last50_r,
            'avg_reward_last_50_std': std_last50,
            'avg_reward_last_50_ci95': float(t_crit * std_last50 / np.sqrt(n_seeds)),
            'avg_cooperation_rate': avg_c,
            'avg_cooperation_rate_std': std_c,
            'avg_betrayal_rate': float(np.mean([s.get('avg_betrayal_rate', 0) for s in summaries])),
            'total_losses': int(np.mean([s.get('total_losses', 0) for s in summaries])),
            'elapsed_time': float(np.mean(elapsed_times)),
        },
        # 每回合级数据（带误差）
        'episode_rewards_mean': reward_mean.tolist(),
        'episode_rewards_std': reward_std.tolist(),
        'episode_rewards_ci95': ci.tolist(),
        'cooperation_rates_mean': coop_mean.tolist(),
        'cooperation_rates_std': coop_std.tolist(),
        # 原始数据（绘图用）
        'episode_rewards': [d['episode_rewards'][:n_episodes] for d in all_data],  # per-seed
        'cooperation_rates': [d['cooperation_rates'][:n_episodes] for d in all_data],
        'bc_scores_history': all_data[0].get('bc_scores_history', []),
        'losses': all_data[0].get('losses', []),
    }

    # 合并区块链统计（取第一个种子的数据）
    first = all_data[0]
    for key in ['ecdsa_stats', 'security_stats', 'consensus_stats', 'blockchain_stats',
                'leaderboard', 'bc_scores_final']:
        if key in first:
            combined[key] = first[key]

    return combined


def main():
    start_time = time.time()
    total_runs = len(MODES) * len(SEEDS)

    logger.info("=" * 60)
    logger.info(f"多种子训练开始: {len(MODES)}模式 × {len(SEEDS)}种子 × {N_EPISODES}回合")
    logger.info(f"种子: {SEEDS}")
    logger.info(f"模式: {MODES}")
    logger.info("=" * 60)

    # ── 阶段1：批量训练 ──
    all_seed_results = {}  # {mode: [path1, path2, path3]}

    for mode in MODES:
        all_seed_results[mode] = []
        for seed in SEEDS:
            path = train_one_seed(mode, seed, N_EPISODES)
            all_seed_results[mode].append(path)

    # ── 阶段2：合并结果 ──
    logger.info("=" * 60)
    logger.info("合并多种子结果...")
    logger.info("=" * 60)

    combined_results = {}
    for mode in MODES:
        combined = combine_results(mode, all_seed_results[mode])
        if combined:
            combined_results[mode] = combined
            output_path = RESULTS_DIR / f'training_results_{mode}_combined.json'
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(combined, f, indent=2, ensure_ascii=False, default=str)
            logger.info(f"[{mode}] 合并完成 → {output_path}")

    # ── 阶段3：生成汇总报告 ──
    logger.info("=" * 60)
    logger.info("训练结果汇总报告")
    logger.info("=" * 60)

    report = {
        'timestamp': datetime.now().isoformat(),
        'n_episodes': N_EPISODES,
        'n_seeds_per_mode': len(SEEDS),
        'seeds': SEEDS,
        'modes': {},
    }

    for mode in MODES:
        if mode in combined_results:
            c = combined_results[mode]
            s = c['summary']
            report['modes'][mode] = {
                'avg_reward': f"{s['avg_reward']:.2f} ± {s['avg_reward_std']:.2f}",
                'avg_reward_ci95': f"[{s['avg_reward'] - s['avg_reward_ci95']:.2f}, {s['avg_reward'] + s['avg_reward_ci95']:.2f}]",
                'avg_reward_last_50': f"{s['avg_reward_last_50']:.2f} ± {s['avg_reward_last_50_std']:.2f}",
                'cooperation_rate': f"{s['avg_cooperation_rate']:.1%} ± {s['avg_cooperation_rate_std']:.1%}",
                'elapsed': f"{s['elapsed_time']:.0f}s",
            }

    # 计算 BC vs Pure 提升
    if 'pure_marl' in combined_results and 'bc_marl' in combined_results:
        p = combined_results['pure_marl']['summary']
        b = combined_results['bc_marl']['summary']
        improve = (b['avg_reward'] - p['avg_reward']) / abs(p['avg_reward']) * 100 if abs(p['avg_reward']) > 0.001 else 0
        report['bc_improvement'] = f"{improve:.1f}%"
        logger.info(f"\n★ BC-MARL vs Pure MARL 提升: {improve:.1f}%")
        logger.info(f"  Pure:  {p['avg_reward']:.2f} ± {p['avg_reward_std']:.2f}")
        logger.info(f"  BC:    {b['avg_reward']:.2f} ± {b['avg_reward_std']:.2f}")
        logger.info(f"  Last50 Pure: {p['avg_reward_last_50']:.2f} | BC: {b['avg_reward_last_50']:.2f}")

    report_path = RESULTS_DIR / 'training_report.json'
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info(f"\n汇总报告: {report_path}")

    total_elapsed = time.time() - start_time
    logger.info(f"\n总耗时: {total_elapsed:.0f}s ({total_elapsed/60:.1f}分钟)")

    return combined_results


if __name__ == '__main__':
    main()

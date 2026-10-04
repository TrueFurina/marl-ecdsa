"""
V2 参数多种子验证实验
基于已验证的 V2 参数（λ=0.1），用多个种子验证 bc_marl vs pure_marl 的提升效果

用法：python train_v2_validation.py
输出：results/v2_validation/ 目录下的各种子结果 + 合并报告
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

sys.path.insert(0, str(Path(__file__).parent))

from train import TrainingConfig, MARLBlockchainTrainer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('v2_validation')

BASE_DIR = _Path(_REPO_ROOT)
OUTPUT_DIR = BASE_DIR / 'results' / 'v2_validation'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# =============================================================================
# V2 验证参数（与 V2 训练一致）
# =============================================================================
SEEDS = [42, 123, 456, 789, 1024]  # 5 个种子
N_EPISODES = 500  # 验证用（比竞赛 1000 少，但足以观察趋势）
LAMBDA_BC = 0.1   # V2 有效 λ

# 通用训练参数（与 V2 一致）
BASE_PARAMS = dict(
    n_agents=3, n_landmarks=3, max_steps=25,
    hidden_dim=128, lr=1e-3, gamma=0.8, batch_size=64,
    epsilon_start=1.0, epsilon_end=0.05, epsilon_decay=5000,
    log_interval=50,
)


def train_one(mode, seed, lambda_w):
    """训练单个 (mode, seed) 组合"""
    config = TrainingConfig(
        **BASE_PARAMS,
        n_episodes=N_EPISODES,
        mode=mode,
        seed=seed,
        lambda_weight=lambda_w,
        selfish_ratio=0.0,
    )
    logger.info(f"[{mode}] seed={seed} λ={lambda_w} 开始训练...")
    t0 = time.time()
    trainer = MARLBlockchainTrainer(config)
    stats = trainer.train()
    elapsed = time.time() - t0

    # 导出结果
    fname = f'{mode}_seed{seed}_lam{lambda_w}.json'
    path = OUTPUT_DIR / fname
    trainer.export_results(str(path))
    trainer.cleanup()

    summary = stats.summary()
    logger.info(f"[{mode}] seed={seed} 完成 ({elapsed:.0f}s) | "
                f"avg_reward={summary['avg_reward']:.2f} | "
                f"last50={summary['avg_reward_last_50']:.2f}")

    return str(path), summary, elapsed


def main():
    t_total = time.time()
    logger.info("=" * 60)
    logger.info(f"V2 参数多种子验证: {len(SEEDS)} seeds × 2 modes × {N_EPISODES} eps")
    logger.info(f"种子: {SEEDS}")
    logger.info(f"λ_pure=0.0, λ_bc={LAMBDA_BC}")
    logger.info("=" * 60)

    results = {'pure_marl': [], 'bc_marl': []}

    for seed in SEEDS:
        # Pure MARL
        path, summary, elapsed = train_one('pure_marl', seed, 0.0)
        results['pure_marl'].append({
            'seed': seed, 'path': path, 'summary': summary, 'elapsed': elapsed
        })
        # BC-MARL
        path, summary, elapsed = train_one('bc_marl', seed, LAMBDA_BC)
        results['bc_marl'].append({
            'seed': seed, 'path': path, 'summary': summary, 'elapsed': elapsed
        })

    # ── 汇总分析 ──
    logger.info("\n" + "=" * 60)
    logger.info("V2 验证结果汇总")
    logger.info("=" * 60)

    def aggregate(mode_results):
        avg_r = [r['summary']['avg_reward'] for r in mode_results]
        last50 = [r['summary'].get('avg_reward_last_50', 0) for r in mode_results]
        coop = [r['summary']['avg_cooperation_rate'] for r in mode_results]
        arr_r, arr_50, arr_c = np.array(avg_r), np.array(last50), np.array(coop)
        return {
            'avg_reward_mean': float(arr_r.mean()),
            'avg_reward_std': float(arr_r.std(ddof=1)),
            'avg_reward_last50_mean': float(arr_50.mean()),
            'avg_reward_last50_std': float(arr_50.std(ddof=1)),
            'cooperation_mean': float(arr_c.mean()),
            'cooperation_std': float(arr_c.std(ddof=1)),
            'per_seed': [{
                'seed': r['seed'],
                'avg_reward': r['summary']['avg_reward'],
                'last50': r['summary'].get('avg_reward_last_50', 0),
                'coop': r['summary']['avg_cooperation_rate'],
            } for r in mode_results],
        }

    pure_agg = aggregate(results['pure_marl'])
    bc_agg = aggregate(results['bc_marl'])

    # BC 提升计算
    improve = (bc_agg['avg_reward_mean'] - pure_agg['avg_reward_mean']) / abs(pure_agg['avg_reward_mean']) * 100
    improve_last50 = (bc_agg['avg_reward_last50_mean'] - pure_agg['avg_reward_last50_mean']) / abs(pure_agg['avg_reward_last50_mean']) * 100

    report = {
        'timestamp': datetime.now().isoformat(),
        'n_episodes': N_EPISODES,
        'n_seeds': len(SEEDS),
        'seeds': SEEDS,
        'lambda_bc': LAMBDA_BC,
        'pure_marl': pure_agg,
        'bc_marl': bc_agg,
        'bc_improvement_pct': round(improve, 1),
        'bc_improvement_last50_pct': round(improve_last50, 1),
        'total_time_s': round(time.time() - t_total, 0),
    }

    report_path = OUTPUT_DIR / 'v2_validation_report.json'
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # 打印汇总
    logger.info(f"\n{'='*60}")
    logger.info(f"Pure MARL:  {pure_agg['avg_reward_mean']:.2f} ± {pure_agg['avg_reward_std']:.2f}  "
                f"(last50: {pure_agg['avg_reward_last50_mean']:.2f})")
    logger.info(f"BC-MARL:    {bc_agg['avg_reward_mean']:.2f} ± {bc_agg['avg_reward_std']:.2f}  "
                f"(last50: {bc_agg['avg_reward_last50_mean']:.2f})")
    logger.info(f"★ BC 提升:  {improve:.1f}% (last50: {improve_last50:.1f}%)")
    logger.info(f"合作率:     Pure={pure_agg['cooperation_mean']:.1%} | BC={bc_agg['cooperation_mean']:.1%}")
    logger.info(f"总耗时:     {time.time() - t_total:.0f}s")
    logger.info(f"报告:       {report_path}")
    logger.info(f"{'='*60}")

    return report


if __name__ == '__main__':
    main()

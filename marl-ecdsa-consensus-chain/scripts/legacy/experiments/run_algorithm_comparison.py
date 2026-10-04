"""
Tier1: IQL vs VDN vs QMIX 三算法对比实验

实验矩阵：
  3算法 (iql/vdn/qmix) × 2模式 (pure_marl/bc_marl) × 3种子 (42/123/456) = 18组
  每组500回合（快速对比，足以展示收敛趋势差异）

输出：
  results/algorithm_comparison/{algo}_{mode}_seed{N}.json
  results/algorithm_comparison/comparison_report.json  (汇总统计)
"""

# ===== 自动注入: 仓库根路径 (legacy 移动兼容) =====
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = str(_Path(__file__).resolve().parent.parent.parent.parent)
if _REPO_ROOT not in _sys.path:
    _sys.path.insert(0, _REPO_ROOT)
# ===== 自动注入结束 =====

import json
import os
import sys
import time
import logging
import subprocess
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('algo_compare')

# 仓库根目录：scripts/legacy/experiments/<file>.py 上溯 4 级
# （原为 Path(__file__).parent = .../legacy/experiments，导致 train.py 找不到、
#   results 落到 legacy 目录下，与仓库 result/ 口径不一致）
PROJECT_ROOT = _Path(__file__).resolve().parent.parent.parent.parent
PYTHON = sys.executable

ALGORITHMS = ['iql', 'vdn', 'qmix']
MODES = ['pure_marl', 'bc_marl']
SEEDS = [42, 123, 456]
N_EPISODES = 500
RUN_TIMEOUT = 1800  # 单组训练子进程超时（秒），原为无超时/默认

RESULTS_DIR = PROJECT_ROOT / 'results' / 'algorithm_comparison'
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def run_single(algo: str, mode: str, seed: int) -> str:
    """运行单组实验"""
    output_file = RESULTS_DIR / f'{algo}_{mode}_seed{seed}.json'

    if output_file.exists():
        logger.info(f"[SKIP] {algo}/{mode}/seed{seed} 已存在")
        return str(output_file)

    cmd = [
        PYTHON, '-X', 'utf8', str(PROJECT_ROOT / 'train.py'),
        '--mode', mode,
        '--seed', str(seed),
        '--n_episodes', str(N_EPISODES),
        '--algorithm', algo,
        '--no-verify-nash',
        '--save', str(output_file),
    ]

    logger.info(f"[RUN] {algo}/{mode}/seed{seed} ({N_EPISODES}ep)")
    start = time.time()
    # -X utf8: Windows 下中文日志按 GBK 解码会崩；MPLCONFIGDIR 避免 matplotlib 缓存踩沙箱
    env = os.environ.copy()
    env.setdefault('MPLCONFIGDIR', str(PROJECT_ROOT / '.mpl_cache'))
    result = subprocess.run(cmd, capture_output=True, cwd=str(PROJECT_ROOT),
                            env=env, encoding='utf-8', errors='replace',
                            timeout=RUN_TIMEOUT)
    elapsed = time.time() - start

    if result.returncode != 0:
        logger.error(f"[FAIL] {algo}/{mode}/seed{seed}: {result.stderr[-500:]}")
        return None

    logger.info(f"[DONE] {algo}/{mode}/seed{seed} in {elapsed:.1f}s")
    return str(output_file)


def generate_report():
    """汇总所有实验结果，计算统计量"""
    import numpy as np
    from scipy import stats as sp_stats

    results = {}
    for algo in ALGORITHMS:
        for mode in MODES:
            key = f'{algo}_{mode}'
            env_rewards_last50 = []
            coop_rates_last50 = []
            files_found = 0

            for seed in SEEDS:
                fpath = RESULTS_DIR / f'{algo}_{mode}_seed{seed}.json'
                if not fpath.exists():
                    continue
                files_found += 1
                with open(fpath) as f:
                    data = json.load(f)
                env_rewards = data.get('env_rewards', [])
                coop_rates = data.get('cooperation_rates', [])
                if len(env_rewards) >= 50:
                    env_rewards_last50.append(np.mean(env_rewards[-50:]))
                if len(coop_rates) >= 50:
                    coop_rates_last50.append(np.mean(coop_rates[-50:]))

            if files_found == 0:
                continue

            results[key] = {
                'algorithm': algo,
                'mode': mode,
                'n_seeds': files_found,
                'env_reward_last50_mean': float(np.mean(env_rewards_last50)) if env_rewards_last50 else None,
                'env_reward_last50_std': float(np.std(env_rewards_last50)) if env_rewards_last50 else None,
                'coop_rate_last50_mean': float(np.mean(coop_rates_last50)) if coop_rates_last50 else None,
                'coop_rate_last50_std': float(np.std(coop_rates_last50)) if coop_rates_last50 else None,
                'seeds_env_rewards': [float(r) for r in env_rewards_last50],
            }

    # 计算 BC 提升幅度（按算法分组）
    for algo in ALGORITHMS:
        pure_key = f'{algo}_pure_marl'
        bc_key = f'{algo}_bc_marl'
        if pure_key in results and bc_key in results:
            pure_mean = results[pure_key]['env_reward_last50_mean']
            bc_mean = results[bc_key]['env_reward_last50_mean']
            if pure_mean is not None and bc_mean is not None and pure_mean != 0:
                improvement = (bc_mean - pure_mean) / abs(pure_mean) * 100
                results[f'{algo}_bc_improvement_pct'] = float(improvement)

            # Welch's t-test
            pure_seeds = results[pure_key]['seeds_env_rewards']
            bc_seeds = results[bc_key]['seeds_env_rewards']
            if len(pure_seeds) >= 2 and len(bc_seeds) >= 2:
                t_stat, p_value = sp_stats.ttest_ind(bc_seeds, pure_seeds, equal_var=False)
                results[f'{algo}_welch_t'] = float(t_stat)
                results[f'{algo}_welch_p'] = float(p_value)

    # 跨算法对比（bc_marl模式下的三算法比较）
    bc_algo_rewards = {}
    for algo in ALGORITHMS:
        key = f'{algo}_bc_marl'
        if key in results and results[key]['env_reward_last50_mean'] is not None:
            bc_algo_rewards[algo] = results[key]['seeds_env_rewards']

    if len(bc_algo_rewards) >= 2:
        results['cross_algorithm_bc'] = {
            algo: rewards for algo, rewards in bc_algo_rewards.items()
        }

    report_path = RESULTS_DIR / 'comparison_report.json'
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info(f"报告已生成: {report_path}")
    return results


def _parse_args(argv=None):
    """命令行覆盖（仅在 __main__ 中调用，避免污染 pytest 的 sys.argv）"""
    import argparse
    p = argparse.ArgumentParser(description='IQL vs VDN vs QMIX 三算法对比')
    p.add_argument('--seeds', type=int, nargs='+', default=None)
    p.add_argument('--n-episodes', type=int, default=None)
    p.add_argument('--algorithms', type=str, nargs='+', default=None)
    p.add_argument('--modes', type=str, nargs='+', default=None)
    p.add_argument('--out-dir', type=str, default=None,
                   help='结果目录；默认 <repo>/results/algorithm_comparison')
    p.add_argument('--timeout', type=int, default=None)
    return p.parse_args(argv)


if __name__ == '__main__':
    _a = _parse_args()
    if _a.seeds is not None:
        SEEDS = _a.seeds
    if _a.n_episodes is not None:
        N_EPISODES = _a.n_episodes
    if _a.algorithms is not None:
        ALGORITHMS = _a.algorithms
    if _a.modes is not None:
        MODES = _a.modes
    if _a.timeout is not None:
        RUN_TIMEOUT = _a.timeout
    if _a.out_dir is not None:
        RESULTS_DIR = Path(_a.out_dir)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    logger.info(f"=== 算法对比实验启动 ===")
    logger.info(f"矩阵: {len(ALGORITHMS)}算法 x {len(MODES)}模式 x {len(SEEDS)}种子 = {len(ALGORITHMS)*len(MODES)*len(SEEDS)}组")
    logger.info(f"每组 {N_EPISODES} 回合")

    total_start = time.time()
    for algo in ALGORITHMS:
        for mode in MODES:
            for seed in SEEDS:
                run_single(algo, mode, seed)

    total_elapsed = time.time() - total_start
    logger.info(f"=== 全部实验完成，耗时 {total_elapsed:.1f}s ===")

    report = generate_report()

    # 打印摘要
    print("\n" + "=" * 70)
    print("算法对比实验结果摘要 (env_reward last50)")
    print("=" * 70)
    print(f"{'算法':<8} {'模式':<12} {'均值':>10} {'标准差':>10} {'BC提升%':>10}")
    print("-" * 70)
    for algo in ALGORITHMS:
        for mode in MODES:
            key = f'{algo}_{mode}'
            if key in report:
                r = report[key]
                mean = r['env_reward_last50_mean']
                std = r['env_reward_last50_std']
                if mean is not None:
                    print(f"{algo:<8} {mode:<12} {mean:>10.2f} {std:>10.2f}", end='')
                    if mode == 'bc_marl' and f'{algo}_bc_improvement_pct' in report:
                        print(f" {report[f'{algo}_bc_improvement_pct']:>9.1f}%", end='')
                    print()

    print("\n" + "=" * 70)
    print("Welch's t-test (bc vs pure)")
    print("=" * 70)
    for algo in ALGORITHMS:
        t_key = f'{algo}_welch_t'
        p_key = f'{algo}_welch_p'
        if t_key in report:
            print(f"  {algo}: t={report[t_key]:.3f}, p={report[p_key]:.4f} {'***' if report[p_key]<0.001 else '**' if report[p_key]<0.01 else '*' if report[p_key]<0.05 else 'ns'}")

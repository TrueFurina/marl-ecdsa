"""
共识感知奖励塑形 (CARS) 对比实验

对比配置：
1. bc_marl (无CARS) — 基准
2. bc_marl + CARS (eta=0.05) — 启用共识感知塑形
3. bc_marl + CARS (eta=0.10) — 强塑形

每组 3 seeds × 500 episodes，使用 env_reward 公平口径对比。

输出：
- results/cars_comparison/cars_comparison_report.json
- 统计显著性检验 (Welch's t-test)
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
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from scipy import stats

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('cars_comparison')

PYTHON = sys.executable
# 仓库根目录：scripts/legacy/experiments/<file>.py 上溯 4 级
# （原 BASE_DIR=Path(__file__).parent → .../legacy/experiments，train.py 找不到）
BASE_DIR = _Path(__file__).resolve().parent.parent.parent.parent
RESULTS_DIR = BASE_DIR / 'results' / 'cars_comparison'
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# 保护已有实验结果：默认绝不覆盖（--overwrite 显式开启才覆盖）
OVERWRITE = False
RUN_TIMEOUT = 1800  # 单组子进程超时（秒），原为硬编码 300


def _safe_write_json(obj, target: Path) -> Path:
    """写 JSON 但绝不覆盖已存在文件：存在时改写为 <stem>_<时间戳>.json"""
    target = Path(target)
    if target.exists() and not OVERWRITE:
        alt = target.with_name(f"{target.stem}_{time.strftime('%Y%m%d_%H%M%S')}{target.suffix}")
        logger.warning(f"[保护] {target.name} 已存在，本次报告另存为 {alt.name}")
        target = alt
    with open(target, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, default=str)
    return target

CONFIGS = [
    {"name": "bc_marl_baseline", "mode": "bc_marl", "consensus_shaping": False, "eta": 0.0},
    {"name": "bc_marl_cars_005", "mode": "bc_marl", "consensus_shaping": True, "eta": 0.05},
    {"name": "bc_marl_cars_010", "mode": "bc_marl", "consensus_shaping": True, "eta": 0.10},
]

SEEDS = [42, 123, 456]
N_EPISODES = 500


def run_single(config_name, mode, seed, consensus_shaping, eta, n_episodes):
    """运行单次实验"""
    output_file = RESULTS_DIR / f"{config_name}_seed{seed}.json"
    if output_file.exists() and not OVERWRITE:
        logger.info(f"[SKIP] {config_name}/seed{seed} 已存在: {output_file.name}")
        return str(output_file)

    cmd = [
        PYTHON, '-X', 'utf8', str(BASE_DIR / 'train.py'),
        '--mode', mode,
        '--seed', str(seed),
        '--n_episodes', str(n_episodes),
        '--save', str(output_file),
    ]
    if consensus_shaping:
        cmd.extend(['--consensus-shaping', '--shaping-eta', str(eta)])

    logger.info(f"[RUN] {config_name}/seed{seed} ({n_episodes}ep)")
    start = time.time()
    # -X utf8: Windows 中文日志按 GBK 解码会崩；MPLCONFIGDIR 规避 matplotlib 缓存沙箱
    env = os.environ.copy()
    env.setdefault('MPLCONFIGDIR', str(BASE_DIR / '.mpl_cache'))
    result = subprocess.run(cmd, capture_output=True, cwd=str(BASE_DIR), env=env,
                            encoding='utf-8', errors='replace', timeout=RUN_TIMEOUT)
    elapsed = time.time() - start

    if result.returncode != 0:
        logger.error(f"[FAIL] {config_name}/seed{seed}: {result.stderr[-200:]}")
        return None

    logger.info(f"[DONE] {config_name}/seed{seed} in {elapsed:.1f}s")
    return str(output_file)


def extract_metrics(filepath):
    """从训练结果JSON中提取关键指标"""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    env_rewards = data.get('env_rewards', [])
    total_rewards = data.get('episode_rewards', [])
    coop_rates = data.get('cooperation_rates', [])
    cars_stats = data.get('consensus_shaping_stats')

    # 取最后50回合的平均值（收敛后性能）
    window = min(50, len(env_rewards))
    return {
        'env_reward_last50': float(np.mean(env_rewards[-window:])) if env_rewards else 0.0,
        'total_reward_last50': float(np.mean(total_rewards[-window:])) if total_rewards else 0.0,
        'coop_rate_last50': float(np.mean(coop_rates[-window:])) if coop_rates else 0.0,
        'env_reward_all': float(np.mean(env_rewards)) if env_rewards else 0.0,
        'coop_rate_all': float(np.mean(coop_rates)) if coop_rates else 0.0,
        'cars_stats': cars_stats,
    }


def welch_ttest(group_a, group_b, name_a, name_b):
    """Welch's t-test"""
    if len(group_a) < 2 or len(group_b) < 2:
        return {"test": "insufficient_data"}
    t_stat, p_value = stats.ttest_ind(group_a, group_b, equal_var=False)
    # 效应量 (Cohen's d)
    pooled_std = np.sqrt(
        ((len(group_a) - 1) * np.var(group_a, ddof=1) +
         (len(group_b) - 1) * np.var(group_b, ddof=1)) /
        (len(group_a) + len(group_b) - 2)
    )
    cohens_d = (np.mean(group_a) - np.mean(group_b)) / pooled_std if pooled_std > 0 else 0.0
    return {
        "t_statistic": float(t_stat),
        "p_value": float(p_value),
        "cohens_d": float(cohens_d),
        # P3-10修复: p_value<0.05 对 numpy 标量返回 np.bool_，json.dump 报告时无法序列化
        "significant": bool(p_value < 0.05),
        "mean_a": float(np.mean(group_a)),
        "mean_b": float(np.mean(group_b)),
        "improvement_pct": float((np.mean(group_a) - np.mean(group_b)) / abs(np.mean(group_b)) * 100) if np.mean(group_b) != 0 else 0.0,
    }


def main(argv=None):
    _apply_args(_parse_args(argv))

    logger.info("=" * 60)
    logger.info("CARS 共识感知奖励塑形对比实验")
    logger.info(f"配置: {len(CONFIGS)} 组 x {len(SEEDS)} seeds = {len(CONFIGS) * len(SEEDS)} 次")
    logger.info(f"每次 {N_EPISODES} 回合")
    logger.info("=" * 60)

    all_results = {}

    for config in CONFIGS:
        config_name = config['name']
        all_results[config_name] = []

        for seed in SEEDS:
            filepath = run_single(
                config_name=config_name,
                mode=config['mode'],
                seed=seed,
                consensus_shaping=config['consensus_shaping'],
                eta=config['eta'],
                n_episodes=N_EPISODES,
            )
            if filepath and os.path.exists(filepath):
                metrics = extract_metrics(filepath)
                metrics['seed'] = seed
                all_results[config_name].append(metrics)

    # 汇总统计
    report = {
        "title": "CARS 共识感知奖励塑形对比实验报告",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n_episodes": N_EPISODES,
        "n_seeds": len(SEEDS),
        "configs": {},
        "statistical_tests": {},
    }

    for config_name, runs in all_results.items():
        if not runs:
            continue
        env_rewards = [r['env_reward_last50'] for r in runs]
        coop_rates = [r['coop_rate_last50'] for r in runs]
        report['configs'][config_name] = {
            'env_reward_last50': {
                'mean': float(np.mean(env_rewards)),
                'std': float(np.std(env_rewards)),
                'values': env_rewards,
            },
            'coop_rate_last50': {
                'mean': float(np.mean(coop_rates)),
                'std': float(np.std(coop_rates)),
                'values': coop_rates,
            },
            'cars_stats': runs[0].get('cars_stats'),
        }

    # 统计检验：CARS vs baseline
    baseline_env = [r['env_reward_last50'] for r in all_results.get('bc_marl_baseline', [])]
    baseline_coop = [r['coop_rate_last50'] for r in all_results.get('bc_marl_baseline', [])]

    for config_name in ['bc_marl_cars_005', 'bc_marl_cars_010']:
        cars_env = [r['env_reward_last50'] for r in all_results.get(config_name, [])]
        cars_coop = [r['coop_rate_last50'] for r in all_results.get(config_name, [])]

        report['statistical_tests'][f'{config_name}_vs_baseline_env_reward'] = welch_ttest(
            cars_env, baseline_env, config_name, 'baseline'
        )
        report['statistical_tests'][f'{config_name}_vs_baseline_coop_rate'] = welch_ttest(
            cars_coop, baseline_coop, config_name, 'baseline'
        )

    # 打印摘要
    print("\n" + "=" * 70)
    print("CARS 共识感知奖励塑形对比实验结果摘要")
    print("=" * 70)
    print(f"{'配置':<25} {'env_reward(last50)':<20} {'合作率(last50)':<20}")
    print("-" * 70)
    for config_name, data in report['configs'].items():
        env_mean = data['env_reward_last50']['mean']
        env_std = data['env_reward_last50']['std']
        coop_mean = data['coop_rate_last50']['mean']
        coop_std = data['coop_rate_last50']['std']
        print(f"{config_name:<25} {env_mean:>8.2f}+/-{env_std:<8.2f} {coop_mean:>8.1%}+/-{coop_std:<8.1%}")
    print("-" * 70)

    print("\n统计检验 (Welch's t-test, CARS vs baseline):")
    for test_name, test_data in report['statistical_tests'].items():
        if isinstance(test_data, dict) and 'p_value' in test_data:
            sig = "***" if test_data['p_value'] < 0.001 else "**" if test_data['p_value'] < 0.01 else "*" if test_data['p_value'] < 0.05 else "ns"
            print(f"  {test_name}: improvement={test_data['improvement_pct']:+.1f}% p={test_data['p_value']:.4f} d={test_data['cohens_d']:.2f} {sig}")

    # 保存报告（不覆盖已有报告）
    report_path = _safe_write_json(report, RESULTS_DIR / 'cars_comparison_report.json')
    logger.info(f"\n报告已保存: {report_path}")
    return report


def _parse_args(argv=None):
    """命令行覆盖（仅在 __main__ 调用，避免污染 pytest 的 sys.argv）"""
    import argparse
    p = argparse.ArgumentParser(description='CARS 共识感知奖励塑形对比')
    p.add_argument('--seeds', type=int, nargs='+', default=None)
    p.add_argument('--n-episodes', type=int, default=None)
    p.add_argument('--out-dir', type=str, default=None,
                   help='结果目录；默认 <repo>/results/cars_comparison')
    p.add_argument('--timeout', type=int, default=None)
    p.add_argument('--overwrite', action='store_true', default=False)
    return p.parse_args(argv)


def _apply_args(_a):
    """把命令行覆盖应用到模块级全局"""
    global SEEDS, N_EPISODES, RESULTS_DIR, OVERWRITE, RUN_TIMEOUT
    if _a.seeds is not None:
        SEEDS = _a.seeds
    if _a.n_episodes is not None:
        N_EPISODES = _a.n_episodes
    if _a.timeout is not None:
        RUN_TIMEOUT = _a.timeout
    OVERWRITE = bool(_a.overwrite)
    if _a.out_dir is not None:
        RESULTS_DIR = Path(_a.out_dir)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


if __name__ == '__main__':
    main()

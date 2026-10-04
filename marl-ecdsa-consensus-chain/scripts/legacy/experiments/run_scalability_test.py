"""
Tier2: 可扩展性测试 — 3/5/8智能体对比实验

验证系统在不同规模下的性能表现：
  - 3 agents (基准) × 3 seeds × 500ep
  - 5 agents × 3 seeds × 500ep
  - 8 agents × 3 seeds × 500ep

对比维度:
  1. env_reward 收敛性能
  2. cooperation_rate 合作率
  3. 区块链吞吐量（交易数/区块数）
  4. 共识开销（CW-PBFT消息数）

输出:
  results/scalability_test/scalability_report.json
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
logger = logging.getLogger('scalability')

PYTHON = sys.executable
# 仓库根（原为 Path(__file__).parent → legacy/experiments，train.py 找不到）
BASE_DIR = _Path(_REPO_ROOT)
RESULTS_DIR = BASE_DIR / 'results' / 'scalability_test'
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# 保护已有实验结果：默认绝不覆盖
OVERWRITE = False
RUN_TIMEOUT = 1800

SEEDS = [42, 123, 456]
N_EPISODES = 500

# 智能体数量与对应路标数
AGENT_CONFIGS = [
    {'n_agents': 3, 'n_landmarks': 3},
    {'n_agents': 5, 'n_landmarks': 5},
    {'n_agents': 8, 'n_landmarks': 8},
]


def run_single(n_agents, n_landmarks, mode, seed, n_episodes, output_file):
    """运行单次实验"""
    output_file = Path(output_file)
    if output_file.exists() and not OVERWRITE:
        logger.info(f"[SKIP] {mode}_a{n_agents}_seed{seed} 已存在: {output_file.name}")
        return str(output_file)

    cmd = [
        PYTHON, '-X', 'utf8', str(BASE_DIR / 'train.py'),
        '--mode', mode,
        '--n_agents', str(n_agents),
        '--n_landmarks', str(n_landmarks),
        '--seed', str(seed),
        '--n_episodes', str(n_episodes),
        '--save', str(output_file),
    ]

    name = f"{mode}_a{n_agents}_seed{seed}"
    logger.info(f"[RUN] {name}")
    start = time.time()
    # -X utf8: Windows 中文日志按 GBK 解码会崩；MPLCONFIGDIR 规避 matplotlib 缓存沙箱
    env = os.environ.copy()
    env.setdefault('MPLCONFIGDIR', str(BASE_DIR / '.mpl_cache'))
    result = subprocess.run(cmd, capture_output=True, cwd=str(BASE_DIR), env=env,
                            encoding='utf-8', errors='replace', timeout=RUN_TIMEOUT)
    elapsed = time.time() - start

    if result.returncode != 0:
        logger.error(f"[FAIL] {name}: {result.stderr[-300:]}")
        return None

    logger.info(f"[DONE] {name} in {elapsed:.1f}s")
    return str(output_file)


def extract_metrics(filepath):
    """提取关键指标"""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    env_rewards = data.get('env_rewards', [])
    total_rewards = data.get('episode_rewards', [])
    coop_rates = data.get('cooperation_rates', [])
    losses = data.get('losses', [])

    blockchain_stats = data.get('blockchain_stats', {})
    consensus_stats = data.get('consensus_stats', {})
    ecdsa_stats = data.get('ecdsa_stats', {})

    window = min(50, len(env_rewards))
    n_agents = data.get('config', {}).get('n_agents', 3)
    n_blocks = blockchain_stats.get('height', 0)
    n_txs = blockchain_stats.get('total_transactions', 0)

    # 每智能体每步交易数
    max_steps = data.get('config', {}).get('max_steps', 25)
    upload_interval = data.get('config', {}).get('upload_interval', 10)
    # 理论交易数 = n_episodes / upload_interval * n_agents * max_steps
    theoretical_txs = (500 // upload_interval) * n_agents * max_steps

    return {
        'n_agents': n_agents,
        'env_reward_last50': float(np.mean(env_rewards[-window:])) if env_rewards else 0.0,
        'env_reward_std_last50': float(np.std(env_rewards[-window:])) if env_rewards else 0.0,
        'env_reward_per_agent': float(np.mean(env_rewards[-window:]) / n_agents) if env_rewards else 0.0,
        'total_reward_last50': float(np.mean(total_rewards[-window:])) if total_rewards else 0.0,
        'coop_rate_last50': float(np.mean(coop_rates[-window:])) if coop_rates else 0.0,
        'coop_rate_std_last50': float(np.std(coop_rates[-window:])) if coop_rates else 0.0,
        'loss_mean': float(np.mean(losses[-window:])) if losses else 0.0,
        'loss_std': float(np.std(losses[-window:])) if losses else 0.0,
        'n_blocks': n_blocks,
        'n_transactions': n_txs,
        'txs_per_block': float(n_txs / max(1, n_blocks)),
        'sign_count': ecdsa_stats.get('sign_count', 0),
        'verify_count': ecdsa_stats.get('verify_count', 0),
        'theoretical_txs': theoretical_txs,
        'elapsed_time': data.get('summary', {}).get('elapsed_time', 0.0),
    }


def welch_ttest(a, b):
    """Welch's t-test"""
    if len(a) < 2 or len(b) < 2:
        return {"test": "insufficient_data"}
    t_stat, p_value = stats.ttest_ind(a, b, equal_var=False)
    pooled_std = np.sqrt(
        ((len(a) - 1) * np.var(a, ddof=1) + (len(b) - 1) * np.var(b, ddof=1)) /
        (len(a) + len(b) - 2)
    )
    cohens_d = (np.mean(a) - np.mean(b)) / pooled_std if pooled_std > 0 else 0.0
    return {
        "t_statistic": float(t_stat),
        "p_value": float(p_value),
        "cohens_d": float(cohens_d),
        "significant": p_value < 0.05,
        "mean_a": float(np.mean(a)),
        "mean_b": float(np.mean(b)),
        "improvement_pct": float((np.mean(a) - np.mean(b)) / abs(np.mean(b)) * 100) if np.mean(b) != 0 else 0.0,
    }


def _run_all_experiments():
    """运行所有实验配置"""
    results = {}
    for config in AGENT_CONFIGS:
        n_agents, n_landmarks = config['n_agents'], config['n_landmarks']
        config_name = f"agents_{n_agents}"
        results[config_name] = {'bc_marl': [], 'pure_marl': []}
        for mode in ['bc_marl', 'pure_marl']:
            for seed in SEEDS:
                output_file = RESULTS_DIR / f"{config_name}_{mode}_seed{seed}.json"
                filepath = run_single(n_agents, n_landmarks, mode, seed, N_EPISODES, output_file)
                if filepath and os.path.exists(filepath):
                    metrics = extract_metrics(filepath)
                    metrics['seed'], metrics['mode'] = seed, mode
                    results[config_name][mode].append(metrics)
    return results


def _build_report(all_results):
    """构建实验报告"""
    report = {"title": "可扩展性测试报告 (3/5/8智能体)", "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
              "n_episodes": N_EPISODES, "n_seeds": len(SEEDS), "configs": {}, "bc_improvement": {}, "statistical_tests": {}}
    for config_name, modes in all_results.items():
        report['configs'][config_name] = {}
        for mode, runs in modes.items():
            if not runs:
                continue
            env_rewards = [r['env_reward_last50'] for r in runs]
            report['configs'][config_name][mode] = {
                'n_agents': runs[0]['n_agents'],
                'env_reward': {'mean': float(np.mean(env_rewards)), 'std': float(np.std(env_rewards)), 'values': env_rewards},
                'coop_rate': {'mean': float(np.mean([r['coop_rate_last50'] for r in runs])), 'std': float(np.std([r['coop_rate_last50'] for r in runs])), 'values': [r['coop_rate_last50'] for r in runs]},
                'avg_elapsed_time': float(np.mean([r['elapsed_time'] for r in runs])),
            }
        bc_env = [r['env_reward_last50'] for r in modes.get('bc_marl', [])]
        pure_env = [r['env_reward_last50'] for r in modes.get('pure_marl', [])]
        if bc_env and pure_env:
            imp = (np.mean(bc_env) - np.mean(pure_env)) / abs(np.mean(pure_env)) * 100
            report['bc_improvement'][config_name] = {'env_reward_improvement_pct': float(imp), 'bc_env_mean': float(np.mean(bc_env)), 'pure_env_mean': float(np.mean(pure_env))}
            report['statistical_tests'][config_name] = welch_ttest(bc_env, pure_env)
    return report


def _print_report(report):
    """打印报告摘要"""
    print("\n" + "=" * 80)
    print("可扩展性测试结果摘要")
    print("=" * 80)
    print(f"{'配置':<15} {'模式':<12} {'env_reward':<20} {'合作率':<15} {'BC提升':<12}")
    print("-" * 80)
    for config_name, modes in report['configs'].items():
        for mode in ['pure_marl', 'bc_marl']:
            data = modes.get(mode, {})
            if not data:
                continue
            env_m, env_s = data['env_reward']['mean'], data['env_reward']['std']
            coop_m, coop_s = data['coop_rate']['mean'], data['coop_rate']['std']
            imp_str = f"{report['bc_improvement'].get(config_name, {}).get('env_reward_improvement_pct', 0):+.1f}%" if mode == 'bc_marl' else ""
            print(f"{data['n_agents']}智能体{'':<9} {'BC-MARL' if mode == 'bc_marl' else 'Pure MARL':<10} {env_m:>8.2f}±{env_s:<8.2f} {coop_m:>6.1%}±{coop_s:<6.1%} {imp_str:<12}")
        print("-" * 80)
    print("\nBC vs Pure 统计检验:")
    for config_name, ttest in report['statistical_tests'].items():
        if 'p_value' in ttest:
            sig = "***" if ttest['p_value'] < 0.001 else "**" if ttest['p_value'] < 0.01 else "*" if ttest['p_value'] < 0.05 else "ns"
            print(f"  {config_name}: improvement={ttest['improvement_pct']:+.1f}% p={ttest['p_value']:.4f} d={ttest['cohens_d']:.2f} {sig}")


def main():
    logger.info("=" * 60)
    logger.info(f"Tier2: 可扩展性测试 ({len(AGENT_CONFIGS)}配置 × {len(SEEDS)} seeds × {N_EPISODES}ep)")
    logger.info("=" * 60)

    all_results = _run_all_experiments()
    report = _build_report(all_results)
    _print_report(report)

    report_path = RESULTS_DIR / 'scalability_report.json'
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    logger.info(f"\n报告已保存: {report_path}")


if __name__ == '__main__':
    main()

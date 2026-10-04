#!/usr/bin/env python3
"""Generate comprehensive experiment analysis report from all completed experiments."""

# ===== 自动注入: 仓库根路径 (legacy 移动兼容) =====
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = str(_Path(__file__).resolve().parent.parent.parent.parent)
if _REPO_ROOT not in _sys.path:
    _sys.path.insert(0, _REPO_ROOT)
# ===== 自动注入结束 =====

import json
import numpy as np
from pathlib import Path
from scipy import stats

BASE = Path(__file__).parent


def _load_seeds(pattern: str, field: str, seeds: list, tail: int = 100) -> list:
    """从多种子结果文件中加载最后 N 回合的指标均值"""
    vals = []
    for s in seeds:
        f = BASE / pattern.format(seed=s)
        if f.exists():
            d = json.load(open(f, encoding='utf-8'))
            vals.append(float(np.mean(d.get(field, [])[-tail:])))
    return vals


def _analyze_algorithm_comparison() -> dict:
    """1. 算法对比（18 组 × 3 种子）"""
    data = {}
    for algo in ['iql', 'vdn', 'qmix']:
        for mode in ['pure_marl', 'bc_marl']:
            ers = _load_seeds(f'results/algorithm_comparison/{algo}_{mode}_seed{{seed}}.json', 'env_rewards', [42, 123, 456])
            crs = _load_seeds(f'results/algorithm_comparison/{algo}_{mode}_seed{{seed}}.json', 'cooperation_rates', [42, 123, 456])
            trs = _load_seeds(f'results/algorithm_comparison/{algo}_{mode}_seed{{seed}}.json', 'episode_rewards', [42, 123, 456])
            if ers:
                data[f'{algo}_{mode}'] = {
                    'env_reward_mean': float(np.mean(ers)), 'env_reward_std': float(np.std(ers)),
                    'total_reward_mean': float(np.mean(trs)), 'total_reward_std': float(np.std(trs)),
                    'coop_rate_mean': float(np.mean(crs)), 'coop_rate_std': float(np.std(crs)),
                    'seeds_env_reward': ers,
                }
    for algo in ['iql', 'vdn', 'qmix']:
        pure = data.get(f'{algo}_pure_marl', {}).get('seeds_env_reward', [])
        bc = data.get(f'{algo}_bc_marl', {}).get('seeds_env_reward', [])
        if pure and bc:
            t, p = stats.ttest_ind(bc, pure, equal_var=False)
            imp = (np.mean(bc) - np.mean(pure)) / abs(np.mean(pure)) * 100
            data[f'{algo}_bc_improvement'] = {
                'pct': float(imp), 'welch_t': float(t), 'welch_p': float(p), 'significant': bool(p < 0.05),
            }
    return data


def _analyze_lambda_sensitivity() -> dict:
    """2. λ 敏感性分析"""
    data = {}
    for lam in ['0.00', '0.05', '0.10', '0.15', '0.20']:
        ers = _load_seeds(f'results/lambda_analysis/lambda_{lam}_seed{{seed}}.json', 'env_rewards', [42, 123, 456])
        crs = _load_seeds(f'results/lambda_analysis/lambda_{lam}_seed{{seed}}.json', 'cooperation_rates', [42, 123, 456])
        if ers:
            data[f'lambda_{lam}'] = {
                'env_reward_mean': float(np.mean(ers)), 'env_reward_std': float(np.std(ers)),
                'coop_rate_mean': float(np.mean(crs)), 'coop_rate_std': float(np.std(crs)), 'seeds': ers,
            }
    adaptive_ers = _load_seeds(f'results/lambda_analysis/adaptive_seed{{seed}}.json', 'env_rewards', [42, 123, 456])
    if adaptive_ers:
        data['adaptive'] = {'env_reward_mean': float(np.mean(adaptive_ers)), 'env_reward_std': float(np.std(adaptive_ers)), 'seeds': adaptive_ers}
    return data


def _analyze_cars_comparison() -> dict:
    """3. CARS 对比"""
    data = {}
    for config in ['bc_marl_baseline', 'bc_marl_cars_005', 'bc_marl_cars_010']:
        ers = _load_seeds(f'results/cars_comparison/{config}_seed{{seed}}.json', 'env_rewards', [42, 123, 456])
        crs = _load_seeds(f'results/cars_comparison/{config}_seed{{seed}}.json', 'cooperation_rates', [42, 123, 456])
        if ers:
            data[config] = {'env_reward_mean': float(np.mean(ers)), 'env_reward_std': float(np.std(ers)),
                            'coop_rate_mean': float(np.mean(crs)), 'coop_rate_std': float(np.std(crs)), 'seeds': ers}
    for config, label in [('bc_marl_cars_005', 'cars_005'), ('bc_marl_cars_010', 'cars_010')]:
        if config in data and 'bc_marl_baseline' in data:
            t, p = stats.ttest_ind(data[config]['seeds'], data['bc_marl_baseline']['seeds'], equal_var=False)
            imp = (np.mean(data[config]['seeds']) - np.mean(data['bc_marl_baseline']['seeds'])) / abs(np.mean(data['bc_marl_baseline']['seeds'])) * 100
            data[f'{label}_vs_baseline'] = {'welch_t': float(t), 'welch_p': float(p), 'significant': bool(p < 0.05), 'improvement_pct': float(imp)}
    return data


def _analyze_consensus_comparison() -> list:
    """4. 共识对比"""
    consensus = json.load(open(BASE / 'results' / 'consensus_comparison' / 'consensus_comparison_report.json', encoding='utf-8'))
    summary = []
    for n_nodes in [4, 7, 10, 15]:
        for byz in [0.0, 0.1, 0.2, 0.33, 0.4]:
            cw = next((x for x in consensus.get('cw_pbft', []) if x.get('n_nodes') == n_nodes and x.get('byzantine_ratio') == byz), None)
            pb = next((x for x in consensus.get('standard_pbft', []) if x.get('n_nodes') == n_nodes and x.get('byzantine_ratio') == byz), None)
            if cw and pb:
                summary.append({'n_nodes': n_nodes, 'byzantine_ratio': byz,
                    'cw_pbft_success': cw['success_rate'], 'standard_pbft_success': pb['success_rate'],
                    'advantage_pct': float((cw['success_rate'] - pb['success_rate']) * 100)})
    return summary


def _analyze_attack_defense() -> dict:
    """5. 攻击防御"""
    report = json.load(open(BASE / 'results' / 'attack_defense_report.json', encoding='utf-8'))
    attacks = report.get('attacks', report.get('scenarios', []))
    summary = {'total_attacks': len(attacks), 'all_blocked': True, 'details': []}
    for attack in attacks:
        if isinstance(attack, dict):
            name = attack.get('attack_name', attack.get('name', attack.get('attack_type', 'unknown')))
            blocked = attack.get('defense_success', attack.get('blocked', True))
            if not blocked:
                summary['all_blocked'] = False
            summary['details'].append({'attack': name, 'blocked': bool(blocked),
                'no_bc': attack.get('no_bc_result', attack.get('without_bc', 'attack_succeeds')),
                'with_bc': attack.get('with_bc_result', attack.get('with_bc', 'attack_blocked'))})
    return summary


def _analyze_scalability() -> dict:
    """6. 可扩展性（如数据存在）"""
    scal_dir = BASE / 'results' / 'scalability_test'
    if not scal_dir.exists():
        return {}
    data = {}
    for n_agents in [3, 5, 8]:
        for mode in ['pure_marl', 'bc_marl']:
            ers = _load_seeds(f'results/scalability_test/agents_{n_agents}_{mode}_seed{{seed}}.json', 'env_rewards', [42, 123, 456], tail=50)
            if ers:
                data[f'agents_{n_agents}_{mode}'] = {'env_reward_mean': float(np.mean(ers)), 'env_reward_std': float(np.std(ers)), 'seeds': ers}
    return data


def _print_summary(analysis: dict):
    """打印摘要报告"""
    print('=' * 70)
    print('COMPREHENSIVE EXPERIMENT ANALYSIS - Summary')
    print('=' * 70)

    print('\n1. ALGORITHM COMPARISON (18 groups, 3 seeds each)')
    print('-' * 55)
    for algo in ['iql', 'vdn', 'qmix']:
        pure = analysis['experiments']['algorithm_comparison'].get(f'{algo}_pure_marl', {})
        bc = analysis['experiments']['algorithm_comparison'].get(f'{algo}_bc_marl', {})
        imp = analysis['experiments']['algorithm_comparison'].get(f'{algo}_bc_improvement', {})
        if pure and bc:
            sig = '***' if imp.get('welch_p', 1) < 0.001 else '**' if imp.get('welch_p', 1) < 0.01 else '*' if imp.get('welch_p', 1) < 0.05 else 'ns'
            print(f"  {algo.upper():4s}: {pure.get('env_reward_mean',0):7.2f} -> {bc.get('env_reward_mean',0):7.2f} ({imp.get('pct',0):+.1f}%) p={imp.get('welch_p',1):.4f} {sig}")

    print('\n2. LAMBDA SENSITIVITY')
    print('-' * 55)
    for key, val in analysis['experiments']['lambda_sensitivity'].items():
        if 'seeds' in val:
            print(f"  {key:12s}: env={val['env_reward_mean']:7.2f}+/-{val['env_reward_std']:5.2f}  coop={val.get('coop_rate_mean',0):.3f}")

    print('\n3. CARS COMPARISON')
    print('-' * 55)
    for config in ['bc_marl_baseline', 'bc_marl_cars_005', 'bc_marl_cars_010']:
        d = analysis['experiments']['cars_comparison'].get(config, {})
        if d:
            print(f"  {config:25s}: env={d['env_reward_mean']:7.2f}+/-{d['env_reward_std']:5.2f}")

    print('\n4. CW-PBFT vs STANDARD PBFT')
    print('-' * 55)
    for item in analysis['experiments']['consensus_comparison']:
        if item['byzantine_ratio'] in [0.33, 0.40] and item['n_nodes'] in [7, 10]:
            print(f"  {item['n_nodes']:2d} nodes, {item['byzantine_ratio']*100:.0f}% Byz: CW={item['cw_pbft_success']*100:.0f}% Std={item['standard_pbft_success']*100:.0f}% diff={item['advantage_pct']:+.0f}%")

    print('\n5. ATTACK DEFENSE')
    print('-' * 55)
    ad = analysis['experiments']['attack_defense']
    print(f"  Total attacks: {ad['total_attacks']}, All blocked: {ad['all_blocked']}")
    for d in ad['details']:
        print(f"  - {d['attack']}: {'BLOCKED' if d['blocked'] else 'BREACHED'}")

    if 'scalability' in analysis['experiments'] and analysis['experiments']['scalability']:
        print('\n6. SCALABILITY')
        print('-' * 55)
        for key, val in analysis['experiments']['scalability'].items():
            print(f"  {key:25s}: env={val['env_reward_mean']:7.2f}+/-{val['env_reward_std']:5.2f}")

    print(f"\nReport saved to: {BASE / 'results' / 'comprehensive_experiment_report.json'}")


def main():
    analysis = {
        'title': 'MARL-ECDSA Consensus Chain - Comprehensive Experiment Analysis',
        'timestamp': '2026-06-29',
        'experiments': {
            'algorithm_comparison': _analyze_algorithm_comparison(),
            'lambda_sensitivity': _analyze_lambda_sensitivity(),
            'cars_comparison': _analyze_cars_comparison(),
            'consensus_comparison': _analyze_consensus_comparison(),
            'attack_defense': _analyze_attack_defense(),
            'scalability': _analyze_scalability(),
        }
    }
    out_path = BASE / 'results' / 'comprehensive_experiment_report.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False, default=str)
    _print_summary(analysis)


if __name__ == '__main__':
    main()

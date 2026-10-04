"""
CW-PBFT 差异化场景实验
对比：在异构智能体场景下，CW-PBFT（贡献度加权）vs 标准 PBFT（等权，--ablate-consensus）

异构设计：agent_2 有 30% 概率执行随机动作（低能力节点）
预期：CW-PBFT 通过加权投票降低低能力节点的影响，训练效果应优于等权 PBFT

用法：
  python scripts/run_heterogeneous_consensus.py --mode cw_pbft --seed 42
  python scripts/run_heterogeneous_consensus.py --mode standard_pbft --seed 42
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Monkey-patch: 用异构环境替换标准环境
from marl.envs import simple_spread
from marl.envs.simple_spread_heterogeneous import SimpleSpreadHeterogeneousEnv

# 保存原始类
_OriginalEnv = simple_spread.SimpleSpreadEnv

# 替换为异构环境（默认 weak_agent_idx=2, weak_noise_rate=0.3）
simple_spread.SimpleSpreadEnv = SimpleSpreadHeterogeneousEnv

# 现在导入 train（它会 import SimpleSpreadEnv，但已经被替换了）
import train


def run_experiment(mode, seed, n_episodes=1000, output_dir='results/heterogeneous_consensus'):
    """
    运行单组实验
    mode: 'cw_pbft' (加权) or 'standard_pbft' (等权, --ablate-consensus)
    """
    os.makedirs(output_dir, exist_ok=True)
    tag = f"{mode}_seed{seed}"
    save_path = os.path.join(output_dir, f"{tag}.json")

    if os.path.exists(save_path):
        print(f"[SKIP] {tag} exists")
        return save_path

    print(f"[RUN] {tag} (mode={mode}, seed={seed}, episodes={n_episodes})")
    start = time.time()

    # 构造 sys.argv
    args = [
        'train.py',
        '--mode', 'bc_marl',
        '--n_agents', '3',
        '--n_landmarks', '3',
        '--n_episodes', str(n_episodes),
        '--seed', str(seed),
        '--algorithm', 'iql',
        '--lambda_weight', '0.1',
        '--save', save_path,
    ]
    if mode == 'standard_pbft':
        args.append('--ablate-consensus')

    sys.argv = args

    try:
        train.main()
        elapsed = time.time() - start
        print(f"[OK] {tag} completed in {elapsed:.1f}s")
        return save_path
    except Exception as e:
        elapsed = time.time() - start
        print(f"[FAIL] {tag}: {e} (elapsed={elapsed:.1f}s)")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['cw_pbft', 'standard_pbft', 'both'], default='both')
    parser.add_argument('--seeds', type=int, nargs='+', default=[42, 123, 456, 7, 8, 9, 14, 15, 16, 17])
    parser.add_argument('--n_episodes', type=int, default=1000)
    parser.add_argument('--output_dir', default='results/heterogeneous_consensus')
    args = parser.parse_args()

    modes = ['cw_pbft', 'standard_pbft'] if args.mode == 'both' else [args.mode]

    results = {}
    for mode in modes:
        mode_results = []
        for seed in args.seeds:
            path = run_experiment(mode, seed, args.n_episodes, args.output_dir)
            if path and os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                s = data.get('summary', data)
                mode_results.append({
                    'seed': seed,
                    'avg_env_reward_last_50': s.get('avg_env_reward_last_50'),
                    'avg_reward_last_50': s.get('avg_reward_last_50'),
                })
        results[mode] = mode_results

    # 统计分析
    if 'cw_pbft' in results and 'standard_pbft' in results:
        import numpy as np
        from scipy import stats

        cw = np.array([r['avg_env_reward_last_50'] for r in results['cw_pbft'] if r['avg_env_reward_last_50'] is not None])
        std = np.array([r['avg_env_reward_last_50'] for r in results['standard_pbft'] if r['avg_env_reward_last_50'] is not None])

        if len(cw) > 0 and len(std) > 0:
            diff = cw.mean() - std.mean()
            t, p = stats.ttest_ind(cw, std, equal_var=False)
            pooled = np.sqrt(((len(cw)-1)*cw.std(ddof=1)**2 + (len(std)-1)*std.std(ddof=1)**2) / (len(cw)+len(std)-2))
            d = diff / pooled if pooled > 0 else 0

            print("\n" + "="*60)
            print("异构场景：CW-PBFT vs 标准 PBFT 对比")
            print("="*60)
            print(f"CW-PBFT (加权):   n={len(cw)}, mean={cw.mean():.3f}, sd={cw.std(ddof=1):.3f}")
            print(f"标准 PBFT (等权): n={len(std)}, mean={std.mean():.3f}, sd={std.std(ddof=1):.3f}")
            print(f"diff={diff:+.3f}, Welch p={p:.4f}, Cohen d={d:.3f}")
            sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"
            print(f"显著性: {sig}")

            # 保存统计结果
            stats_result = {
                'cw_pbft': {'n': len(cw), 'mean': float(cw.mean()), 'sd': float(cw.std(ddof=1))},
                'standard_pbft': {'n': len(std), 'mean': float(std.mean()), 'sd': float(std.std(ddof=1))},
                'diff': float(diff),
                'welch_p': float(p),
                'cohens_d': float(d),
                'significant': p < 0.05,
                'heterogeneous_config': {'weak_agent_idx': 2, 'weak_noise_rate': 0.3}
            }
            with open(os.path.join(args.output_dir, 'comparison_stats.json'), 'w', encoding='utf-8') as f:
                json.dump(stats_result, f, indent=2, ensure_ascii=False)
            print(f"\n统计结果已保存到 {args.output_dir}/comparison_stats.json")


if __name__ == '__main__':
    main()

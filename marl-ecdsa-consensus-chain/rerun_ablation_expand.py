"""
消融实验扩种：n=3 -> n=10
现有 seed: 42, 123, 456 (n=3)
新增 seed: 7, 8, 9, 14, 15, 16, 17 (7个，到 n=10)
4种条件: baseline / security(ablate_security) / consensus(ablate_consensus) / incentive(ablate_incentive)
配置: bc_marl, 500ep, IQL, lambda=0.1, 3 agents
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import train  # noqa: F401

EXISTING_SEEDS = {42, 123, 456}
NEW_SEEDS = [7, 8, 9, 14, 15, 16, 17]
SAVE_DIR = 'results/ablation'

CONDITIONS = [
    # (name, extra_args)
    ('baseline', []),
    ('security', ['--ablate-security']),
    ('consensus', ['--ablate-consensus']),
    ('incentive', ['--ablate-incentive']),
]


def run_one(condition_name, extra_args, seed):
    save = os.path.join(SAVE_DIR, f'{condition_name}_seed{seed}.json')
    if os.path.exists(save):
        print(f'  [skip] {condition_name} seed={seed} exists', flush=True)
        return True
    sys.argv = [
        'train.py',
        '--mode', 'bc_marl',
        '--n_agents', '3',
        '--n_landmarks', '3',
        '--n_episodes', '500',
        '--seed', str(seed),
        '--algorithm', 'iql',
        '--lambda_weight', '0.1',
        '--save', save,
    ] + extra_args
    print(f'  [run] {condition_name} seed={seed} -> {save}', flush=True)
    try:
        train.main()
        return True
    except Exception as e:
        print(f'  [ERROR] {condition_name} seed={seed}: {e}', flush=True)
        return False


def main():
    t0 = time.time()
    os.makedirs(SAVE_DIR, exist_ok=True)
    total = len(NEW_SEEDS) * len(CONDITIONS)
    done = 0

    print(f'=== 消融实验扩种 n=3->n=10 ===', flush=True)
    print(f'新增 seeds: {NEW_SEEDS}', flush=True)
    print(f'条件: {[c[0] for c in CONDITIONS]}', flush=True)
    print(f'总计 {total} 次运行', flush=True)
    print(flush=True)

    for seed in NEW_SEEDS:
        print(f'--- seed={seed} ---', flush=True)
        for cond_name, extra_args in CONDITIONS:
            ok = run_one(cond_name, extra_args, seed)
            done += 1
            if ok:
                print(f'  [progress] {done}/{total} ({time.time()-t0:.0f}s elapsed)', flush=True)

    print(flush=True)
    print(f'=== ALL DONE in {time.time()-t0:.0f}s ===', flush=True)
    print(f'Each condition should now have n={len(EXISTING_SEEDS)+len(NEW_SEEDS)}=10', flush=True)
    print('Next: compute ablation statistics and update PROJECT_TRUTH_SOURCE.md', flush=True)


if __name__ == '__main__':
    main()

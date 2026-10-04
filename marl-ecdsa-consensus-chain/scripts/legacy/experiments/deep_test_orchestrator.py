# -*- coding: utf-8 -*-
"""
深度测试编排器 (Deep Test Orchestrator)
- 支持断点续跑: 已存在的 json 结果自动跳过
- 支持超时保护: 单实验默认 2400s 超时
- 用法:
    python deep_test_orchestrator.py scalability      # 可扩展性补全(5/8智能体)
    python deep_test_orchestrator.py ablation_conv     # 消融 + 3000回合收敛
- 不修改任何核心代码, 仅通过 train.py CLI 触发实验
"""
import subprocess, sys, os, time, json

# 便携化: 使用当前解释器, 避免硬编码本机绝对路径
PYTHON = sys.executable or 'python'
BASE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(BASE, 'results')
os.makedirs(os.path.join(RESULTS, 'ablation'), exist_ok=True)
os.makedirs(os.path.join(RESULTS, 'convergence_3000'), exist_ok=True)


def run_one(tag, args, save_path, timeout=2400):
    if os.path.exists(save_path):
        print(f'[SKIP] {tag} (exists)')
        return 'skip'
    cmd = [PYTHON, os.path.join(BASE, 'train.py')] + args
    print(f'[START {time.strftime("%H:%M:%S")}] {tag}', flush=True)
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=BASE)
        el = time.time() - t0
        if r.returncode != 0:
            print(f'[FAIL] {tag} ({el:.0f}s): {r.stderr[-400:]}', flush=True)
            return 'fail'
        print(f'[DONE] {tag} ({el:.0f}s)', flush=True)
        return 'ok'
    except subprocess.TimeoutExpired:
        print(f'[TIMEOUT] {tag} (>{timeout}s)', flush=True)
        return 'timeout'


def build_scalability():
    exps = []
    for n in [5, 8]:
        for mode in ['pure_marl', 'bc_marl']:
            for seed in [42, 123, 456]:
                sp = os.path.join(RESULTS, 'scalability_test', f'agents_{n}_{mode}_seed{seed}.json')
                exps.append((f'scal_{n}_{mode}_s{seed}',
                             ['--mode', mode, '--n_agents', str(n), '--n_landmarks', str(n),
                              '--seed', str(seed), '--n_episodes', '500', '--save', sp], sp))
    return exps


def build_ablation_conv():
    exps = []
    # 消融: 3智能体 bc_marl, 分别禁用三模块
    abl = {'security': ['--ablate-security'], 'consensus': ['--ablate-consensus'], 'incentive': ['--ablate-incentive']}
    for name, flag in abl.items():
        for seed in [42, 123, 456]:
            sp = os.path.join(RESULTS, 'ablation', f'{name}_seed{seed}.json')
            exps.append((f'abl_{name}_s{seed}',
                         ['--mode', 'bc_marl', '--n_agents', '3', '--n_landmarks', '3',
                          '--seed', str(seed), '--n_episodes', '500', '--save', sp] + flag, sp))
    # baseline (bc_marl 完整, 无消融)
    for seed in [42, 123, 456]:
        sp = os.path.join(RESULTS, 'ablation', f'baseline_seed{seed}.json')
        exps.append((f'abl_baseline_s{seed}',
                     ['--mode', 'bc_marl', '--n_agents', '3', '--n_landmarks', '3',
                      '--seed', str(seed), '--n_episodes', '500', '--save', sp], sp))
    # 3000回合收敛验证
    for mode in ['pure_marl', 'bc_marl']:
        for seed in [42, 123, 456]:
            sp = os.path.join(RESULTS, 'convergence_3000', f'{mode}_seed{seed}.json')
            exps.append((f'conv3000_{mode}_s{seed}',
                         ['--mode', mode, '--n_agents', '3', '--n_landmarks', '3',
                          '--seed', str(seed), '--n_episodes', '3000', '--save', sp], sp))
    return exps


def build_hp_sweep():
    """超参鲁棒性扫描: bc_marl 3智能体, 扫描 gamma/lr (baseline γ=0.8,lr=1e-3 已由 abl_baseline 覆盖)"""
    exps = []
    configs = [
        ('g0.9_lr1e-3', ['--gamma', '0.9', '--lr', '1e-3']),
        ('g0.8_lr5e-4', ['--gamma', '0.8', '--lr', '5e-4']),
        ('g0.9_lr5e-4', ['--gamma', '0.9', '--lr', '5e-4']),
    ]
    for name, flag in configs:
        for seed in [42, 123, 456]:
            sp = os.path.join(RESULTS, 'hp_sweep', f'{name}_seed{seed}.json')
            exps.append((f'hp_{name}_s{seed}',
                         ['--mode', 'bc_marl', '--n_agents', '3', '--n_landmarks', '3',
                          '--seed', str(seed), '--n_episodes', '500', '--save', sp] + flag, sp))
    return exps


def main():
    tier = sys.argv[1] if len(sys.argv) > 1 else 'scalability'
    if tier == 'scalability':
        exps = build_scalability()
    elif tier == 'ablation_conv':
        exps = build_ablation_conv()
    elif tier == 'hp_sweep':
        os.makedirs(os.path.join(RESULTS, 'hp_sweep'), exist_ok=True)
        exps = build_hp_sweep()
    else:
        print(f'Unknown tier: {tier}')
        sys.exit(1)

    print(f'=== Deep Test Orchestrator: {tier} ({len(exps)} experiments) ===', flush=True)
    summary = {'ok': 0, 'skip': 0, 'fail': 0, 'timeout': 0}
    for tag, args, sp in exps:
        res = run_one(tag, args, sp, timeout=3000)
        summary[res] = summary.get(res, 0) + 1
    print('=== SUMMARY ===', json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()

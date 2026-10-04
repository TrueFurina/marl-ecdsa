# -*- coding: utf-8 -*-
"""
深度测试驱动器 (单进程复用 torch, 避免后台 import 崩溃)
- 前台 import train (torch 在前台加载一次)
- 同进程内循环调用 train.main() 跑全部实验, 无需重复 import torch
- 断点续跑: 结果文件已存在则跳过
- 用法: python deep_test_driver.py   (前台启动, 超时转后台仍安全)
"""

# ===== 自动注入: 仓库根路径 (legacy 移动兼容) =====
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = str(_Path(__file__).resolve().parent.parent.parent.parent)
if _REPO_ROOT not in _sys.path:
    _sys.path.insert(0, _REPO_ROOT)
# ===== 自动注入结束 =====

import os
import sys
import time
import json
import importlib

BASE = _REPO_ROOT
RESULTS = os.path.join(BASE, 'results')
for d in ['scalability_test', 'ablation', 'convergence_3000', 'hp_sweep']:
    os.makedirs(os.path.join(RESULTS, d), exist_ok=True)

# 前台一次性 import (torch 在此加载, 后台不再重载)
import train  # noqa: E402


def _expected_episodes(argv):
    for i, a in enumerate(argv):
        if a == '--n_episodes' and i + 1 < len(argv):
            try:
                return int(argv[i + 1])
            except ValueError:
                return None
    return None


def run(argv, save):
    expected = _expected_episodes(argv)
    # 断点续跑 + 回合校验: 文件存在但回合数不符 → 视为陈旧, 删除重跑
    if os.path.exists(save):
        try:
            with open(save, encoding='utf-8') as f:
                data = json.load(f)
            ep = data.get('summary', {}).get('total_episodes')
            if expected is not None and ep is not None and ep != expected:
                print(f'[STALE] {os.path.basename(save)} episodes={ep}(expect {expected}), deleting', flush=True)
                os.remove(save)
            else:
                print(f'[SKIP] {os.path.basename(save)}', flush=True)
                return 'skip'
        except Exception:
            print(f'[CORRUPT] {os.path.basename(save)}, deleting', flush=True)
            os.remove(save)
    sys.argv = ['train.py'] + argv + ['--save', save]
    try:
        train.main()
        if os.path.exists(save):
            print(f'[DONE] {os.path.basename(save)}', flush=True)
            return 'ok'
        print(f'[NOFILE] {os.path.basename(save)}', flush=True)
        return 'nofile'
    except SystemExit:
        if os.path.exists(save):
            print(f'[DONE] {os.path.basename(save)} (exit)', flush=True)
            return 'ok'
        return 'exit'
    except Exception as e:
        print(f'[FAIL] {os.path.basename(save)}: {e}', flush=True)
        return 'fail'


def build():
    exps = []
    # Tier1: scalability
    for n in [5, 8]:
        for mode in ['pure_marl', 'bc_marl']:
            for seed in [42, 123, 456]:
                exps.append((['--mode', mode, '--n_agents', str(n), '--n_landmarks', str(n),
                              '--seed', str(seed), '--n_episodes', '500'],
                             os.path.join(RESULTS, 'scalability_test', f'agents_{n}_{mode}_seed{seed}.json')))
    # Tier2: ablation (bc_marl, 3 agents, 500ep)
    for seed in [42, 123, 456]:
        exps.append((['--mode', 'bc_marl', '--n_agents', '3', '--n_landmarks', '3',
                      '--seed', str(seed), '--n_episodes', '500'],
                     os.path.join(RESULTS, 'ablation', f'baseline_seed{seed}.json')))
    for mod in ['security', 'consensus', 'incentive']:
        for seed in [42, 123, 456]:
            exps.append((['--mode', 'bc_marl', '--n_agents', '3', '--n_landmarks', '3',
                          '--seed', str(seed), '--n_episodes', '500', f'--ablate-{mod}'],
                         os.path.join(RESULTS, 'ablation', f'{mod}_seed{seed}.json')))
    # Tier3: convergence 3000ep
    for mode in ['pure_marl', 'bc_marl']:
        for seed in [42, 123, 456]:
            exps.append((['--mode', mode, '--n_agents', '3', '--n_landmarks', '3',
                          '--seed', str(seed), '--n_episodes', '3000'],
                         os.path.join(RESULTS, 'convergence_3000', f'{mode}_seed{seed}.json')))
    # Tier4: hyperparam sweep (bc_marl, 3 agents, 500ep)
    hp = [('g0.9_lr1e-3', ['--gamma', '0.9', '--lr', '1e-3']),
          ('g0.8_lr5e-4', ['--gamma', '0.8', '--lr', '5e-4']),
          ('g0.9_lr5e-4', ['--gamma', '0.9', '--lr', '5e-4'])]
    for name, flag in hp:
        for seed in [42, 123, 456]:
            exps.append((['--mode', 'bc_marl', '--n_agents', '3', '--n_landmarks', '3',
                          '--seed', str(seed), '--n_episodes', '500'] + flag,
                         os.path.join(RESULTS, 'hp_sweep', f'{name}_seed{seed}.json')))
    return exps


def main():
    exps = build()
    print(f'=== Deep Test Driver: {len(exps)} experiments (torch loaded in foreground) ===', flush=True)
    summary = {'ok': 0, 'skip': 0, 'fail': 0, 'nofile': 0, 'exit': 0}
    for i, (argv, save) in enumerate(exps):
        t0 = time.time()
        res = run(argv, save)
        summary[res] = summary.get(res, 0) + 1
        print(f'[{i+1}/{len(exps)}] {res} ({time.time()-t0:.0f}s)', flush=True)
    print('=== SUMMARY ===', summary, flush=True)


if __name__ == '__main__':
    main()

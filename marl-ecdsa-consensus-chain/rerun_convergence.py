"""
聚焦重测：3000ep 收敛验证（bc_marl vs pure_marl × 3 seed）
P0-B 修复后，用「行为相关激励」重测，使头号指标 +XX% 具备机制支撑。

绕过 torch 后台 import 崩溃：前台 import train（torch 前台加载），
同进程循环调用 train.main()（改 sys.argv 传参），超时自动转后台后 torch 已加载不再崩。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 前台加载 torch（关键：避免后台 import 阶段 SIGSEGV）
import train  # noqa: F401

CONFIGS = [
    ('bc_marl', 42), ('bc_marl', 123), ('bc_marl', 456),
    ('pure_marl', 42), ('pure_marl', 123), ('pure_marl', 456),
]
SAVE_DIR = 'results/convergence_3000'


def main():
    os.makedirs(SAVE_DIR, exist_ok=True)
    for mode, seed in CONFIGS:
        save = os.path.join(SAVE_DIR, f'{mode}_seed{seed}.json')
        # 删除旧(常数激励)结果，强制用新激励重测
        if os.path.exists(save):
            os.remove(save)
        sys.argv = [
            'train.py',
            '--mode', mode,
            '--n_agents', '3',
            '--n_landmarks', '3',
            '--n_episodes', '3000',
            '--seed', str(seed),
            '--algorithm', 'iql',
            '--save', save,
        ]
        print(f'[rerun] START {mode} seed={seed} -> {save}', flush=True)
        train.main()
        print(f'[rerun] DONE  {mode} seed={seed}', flush=True)
    print('[rerun] ALL CONVERGENCE RUNS COMPLETE', flush=True)


if __name__ == '__main__':
    main()

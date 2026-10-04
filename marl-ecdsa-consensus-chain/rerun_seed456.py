"""
补跑：pure_marl seed456（3000ep），与现有 3 bc + 2 pure 凑成 3v3 收敛数据集。
前台 import train（torch 前台加载），绕过后台 import 崩溃。
只跑这一个 config，不动其它已生成文件。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 前台加载 torch（关键：避免后台 import 阶段 SIGSEGV）
import train  # noqa: F401

SAVE_DIR = 'results/convergence_3000'


def main():
    os.makedirs(SAVE_DIR, exist_ok=True)
    mode, seed = 'pure_marl', 456
    save = os.path.join(SAVE_DIR, f'{mode}_seed{seed}.json')
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


if __name__ == '__main__':
    main()

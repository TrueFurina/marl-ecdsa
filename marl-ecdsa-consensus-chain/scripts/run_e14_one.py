"""
E14 跨算法扩种 —— 单跑助手
==========================
为 IQL / VDN / MAPPO 三个算法补齐 n=10 → n=20（新增 seed 110-119），
使跨算法对比四行（NR-63 QMIX / NR-64 IQL / NR-65 VDN / NR-66 MAPPO）
全部达到 n=20/组，具备可比样本量与检验力。

输出命名与既有 E14 批次完全一致（复用同一 results 目录，登记簿 glob 自动生效）：
  bc_marl   -> results/dispatch_20260921/e14_<algo>_seed<NNN>.json
  pure_marl -> results/dispatch_20260921/e14pure_<algo>_seed<NNN>.json

配置严格对齐既有 E14（见 e14_iql_seed100.json 的 config）：
  n_agents=3, n_landmarks=3, n_episodes=3000, lambda_weight=0.1, max_steps=25

用法（一般由 run_e14_expand_n20.sh 并行调度，不建议手工单跑）：
    python scripts/run_e14_one.py --algo iql --mode bc_marl --seed 110
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import train  # noqa: E402  前台加载 torch，避免后台并行时 SIGSEGV

DEFAULT_OUT = 'results/dispatch_20260921'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--algo', required=True, choices=['iql', 'vdn', 'qmix', 'mappo'])
    ap.add_argument('--mode', required=True, choices=['bc_marl', 'pure_marl'])
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--n_episodes', type=int, default=3000)
    ap.add_argument('--out_dir', default=DEFAULT_OUT)
    args = ap.parse_args()

    tag = 'e14' if args.mode == 'bc_marl' else 'e14pure'
    save_path = os.path.join(args.out_dir,
                             f'{tag}_{args.algo}_seed{args.seed}.json')
    if os.path.exists(save_path):
        print(f'[skip] {save_path} exists')
        return 0

    sys.argv = [
        'train.py',
        '--mode', args.mode,
        '--n_agents', '3',
        '--n_landmarks', '3',
        '--n_episodes', str(args.n_episodes),
        '--seed', str(args.seed),
        '--algorithm', args.algo,
        '--lambda_weight', '0.1',
        '--save', save_path,
    ]
    print(f'[run] {args.algo} {args.mode} seed={args.seed} -> {save_path}', flush=True)
    try:
        train.main()
    except Exception as e:
        print(f'[ERROR] {args.algo} {args.mode} seed={args.seed}: {e}', flush=True)
        return 1
    print(f'[ok] {args.algo} {args.mode} seed={args.seed}', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())

"""
任务 A｜服务器端环境多样性扩展 —— 运行脚本（不修改 train.py）。

用法（在仓库根目录执行）：
  python scripts/run_env_diversity.py --env moving3 --mode bc_marl --seed 42 --n_episodes 3000
  python scripts/run_env_diversity.py --env moving5 --mode pure_marl --seed 43 --n_episodes 3000

设计要点：
- EnvDivTrainer 继承 MARLBlockchainTrainer，仅用 SimpleSpreadMovingEnv 替换 self.env。
  两个环境的 obs/state/action 维度完全一致，因此 QMIXTrainer / BC 桥接 / 合作检测
  等全部复用，无需改动现有代码。
- 输出文件名：<out_dir>/<env>_<mode>_seed<seed>.json，与现有 results 约定一致。
- 主指标统一 env_reward（不含 BC 激励）；λ=0.1；算法默认 qmix（BC 增益最显著、最值得做泛化）。
"""
import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 仓库根

from train import MARLBlockchainTrainer, TrainingConfig  # noqa: E402
from marl.envs.simple_spread_variants import SimpleSpreadMovingEnv  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger('run_env_diversity')

# 环境多样性配置：在"动态目标"这一第二个环境上做规模扫描
ENV_SPECS = {
    'moving3': dict(n_agents=3, n_landmarks=3),
    'moving5': dict(n_agents=5, n_landmarks=5),
}


class EnvDivTrainer(MARLBlockchainTrainer):
    """仅替换环境为动态目标变体；其余 BC 集成完全复用父类。"""

    def __init__(self, config: TrainingConfig, spec: dict):
        self._spec = spec
        super().__init__(config)
        na, nl = spec['n_agents'], spec['n_landmarks']
        self.env = SimpleSpreadMovingEnv(
            n_agents=na, n_landmarks=nl,
            max_steps=config.max_steps, seed=config.seed,
        )
        logger.info(f"[EnvDiv] 环境已替换为 SimpleSpreadMovingEnv({na}x{nl})")


def main():
    ap = argparse.ArgumentParser(description='环境多样性扩展运行脚本')
    ap.add_argument('--env', required=True, choices=list(ENV_SPECS.keys()))
    ap.add_argument('--mode', default='bc_marl', choices=['bc_marl', 'pure_marl'])
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--n_episodes', type=int, default=3000)
    ap.add_argument('--algorithm', default='qmix', choices=['iql', 'vdn', 'qmix'])
    ap.add_argument('--lambda_weight', type=float, default=0.1,
                    help='竞赛基准 λ=0.1')
    ap.add_argument('--max_steps', type=int, default=25)
    ap.add_argument('--out_dir', default='results/env_diversity_20260927')
    ap.add_argument('--no-verify-nash', action='store_true')
    args = ap.parse_args()

    spec = ENV_SPECS[args.env]
    cfg = TrainingConfig(
        n_agents=spec['n_agents'], n_landmarks=spec['n_landmarks'],
        n_episodes=args.n_episodes, max_steps=args.max_steps,
        hidden_dim=128, lr=1e-3, gamma=0.8, batch_size=64,
        lambda_weight=args.lambda_weight, upload_interval=10,
        selfish_ratio=0.0, mode=args.mode, seed=args.seed, log_interval=10,
        # 与主实验一致：自适应λ 默认启用；Nash 验证默认启用（可被 --no-verify-nash 关）
        adaptive_lambda=True, verify_nash=not args.no_verify_nash,
        algorithm=args.algorithm,
    )

    os.makedirs(args.out_dir, exist_ok=True)
    save = os.path.join(
        args.out_dir, f"{args.env}_{args.mode}_seed{args.seed}.json"
    )
    logger.info(f"[EnvDiv] 启动 | env={args.env} mode={args.mode} "
                f"seed={args.seed} ep={args.n_episodes} algo={args.algorithm}")

    trainer = EnvDivTrainer(cfg, spec)
    trainer.train()
    trainer.export_results(save)
    trainer.cleanup()
    logger.info(f"[EnvDiv] 结果已导出: {save}")


if __name__ == '__main__':
    main()

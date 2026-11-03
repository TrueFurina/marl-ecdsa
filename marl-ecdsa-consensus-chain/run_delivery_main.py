"""
配送场景主证据训练入口（完整 BC 链路）

与 train.py 完全同源：仅将环境替换为 DeliveryMARLEnv（骑手-无人机协同，3 智能体），
其余（ECDSA 签名桥接、激励合约、SecurityGuard、CW-PBFT 共识、合作率检测、CARS 塑形）
全部复用 MARLBlockchainTrainer，保证配送场景证据与主证据（SimpleSpread 家族）
同口径可比：主指标 avg_env_reward_last_50（不含 BC 激励）。

用法（在仓库根目录执行，参数与 train.py 一致，仅环境不同）：
  python run_delivery_main.py --mode bc_marl --algorithm iql --seed 3001 \
      --n_episodes 3000 --max_steps 60 --lambda_weight 0.1 \
      --save results/delivery_main/e32_iql_bc_seed3001.json

说明：
  - 配送环境为确定性环境（固定订单/起点），种子差异来自网络初始化与探索序列；
  - max_steps 务必显式传 60（config.json 默认值为 SimpleSpread 的 25）；
  - 预注册见 docs/PREREG_E32_delivery_main.md。
"""
import argparse
import json
import logging
import os
import signal
import sys
from pathlib import Path

# 训练进程线程限制：批量并发跑时避免 torch 默认线程池撑爆 128 核（load>500 踩坑）
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "2")

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train import (  # noqa: E402
    MARLBlockchainTrainer,
    TrainingConfig,
    TrainingStats,
    parse_args,
)
from marl.envs.delivery_env import DeliveryAdapterEnv  # noqa: E402
from marl.integration.selfish_agent import SelfishAgentWrapper  # noqa: E402

try:
    import torch

    torch.set_num_threads(2)
except Exception:
    pass

logger = logging.getLogger("run_delivery_main")


class DeliverySelfishWrapper(SelfishAgentWrapper):
    """配送环境专用自私智能体封装。

    覆盖 _greedy_action：配送观测布局为
      obs[0:2]=自身位置, obs[2]=类型, obs[3:5]=当前目标点,
      obs[5:7]=交接点, obs[7:11]=他者位置。
    myopic 贪心 = 朝当前目标点 (obs[3:5]) 做一步最优移动。
    """

    def _greedy_action(self, obs) -> int:
        """配送理性贪心：朝当前目标点做一步曼哈顿最优移动。

        动作映射与 DeliveryMARLEnv._action_deltas 一致：
          0=不动, 1=上(+y 0.08), 2=下(-y 0.08), 3=左(-x 0.08), 4=右(+x 0.08)
        """
        own_x, own_y = float(obs[0]), float(obs[1])
        target_x, target_y = float(obs[3]), float(obs[4])
        dx = target_x - own_x
        dy = target_y - own_y
        step = 0.08  # 与 _action_deltas 一致
        candidates = [
            (0, abs(dx) + abs(dy)),           # no-op
            (1, abs(dx) + abs(dy - step)),    # up: dy 减小
            (2, abs(dx) + abs(dy + step)),    # down: dy 增大
            (3, abs(dx + step) + abs(dy)),   # left: dx 增大
            (4, abs(dx - step) + abs(dy)),   # right: dx 减小
        ]
        return min(candidates, key=lambda t: t[1])[0]


class DeliveryTrainer(MARLBlockchainTrainer):
    """配送场景训练器：仅替换环境，其余链路完全复用父类。

    E40 扩展：覆盖 _init_selfish_agents，允许在 bc_marl / pure_marl 模式下
    注入自私智能体（父类条件锁死 mode=='selfish'）。用于配送场景拜占庭实验：
      - bc_marl + selfish_ratio>0  → 有链上检测惩罚（BC组）
      - pure_marl + selfish_ratio>0 → 无链上检测惩罚（PURE组）
    """

    def __init__(self, config: TrainingConfig):
        self.config = config
        self.stats = TrainingStats()
        np.random.seed(config.seed)

        self.env = DeliveryAdapterEnv(max_steps=config.max_steps)
        self.agent_ids = [f"agent_{i}" for i in range(config.n_agents)]

        self._init_blockchain_components()
        self._init_trainer()
        self._init_network()
        self._init_bridge()
        self._init_selfish_agents()
        self._init_consensus_shaper()

        logger.info(
            f"[DeliveryTrainer] 初始化完成，模式={config.mode}, 算法={config.algorithm}, "
            f"智能体={config.n_agents}, selfish_ratio={config.selfish_ratio}"
        )
        logger.info(
            f"[DeliveryTrainer] 配送环境: obs_dim={self.env.obs_dim}, "
            f"state_dim={self.env.state_dim}, actions={self.env.n_actions}, "
            f"max_steps={config.max_steps}"
        )

    def _init_selfish_agents(self):
        """E40：放开 mode 限制，只要 selfish_ratio>0 就注入自私智能体。"""
        if self.config.selfish_ratio > 0:
            self.selfish_wrappers = self._init_selfish_wrappers()
        else:
            self.selfish_wrappers = None

    def _init_selfish_wrappers(self):
        """覆盖父类：使用 DeliverySelfishWrapper（配送观测布局的 greedy）。

        E41: betrayal_mode 由 config.betrayal_mode 决定（默认 greedy，朝目标点 myopic）。
        E40: 若传 --betrayal_mode random 则退化为随机背叛。
        """
        c = self.config
        n_selfish = max(1, round(c.n_agents * c.selfish_ratio))
        wrappers = []
        mode = getattr(c, 'betrayal_mode', 'greedy')
        for i in range(c.n_agents):
            aid = self.agent_ids[i]
            is_selfish = i < n_selfish
            wrapper = DeliverySelfishWrapper(
                agent_id=aid,
                base_agent=(self.trainer.agents[i] if getattr(self, 'trainer', None) and i < len(self.trainer.agents) else None),
                is_selfish=is_selfish,
                betrayal_prob=0.3 if is_selfish else 0.0,
                n_landmarks=c.n_landmarks,
                betrayal_mode=mode if is_selfish else 'random',
                greedy_step=0.08,
            )
            wrappers.append(wrapper)
        logger.info(f"[DeliveryTrainer] 创建 {n_selfish}/{c.n_agents} 个自私智能体 (mode={mode})")
        return wrappers


def main():
    args = parse_args()
    config = TrainingConfig(
        n_agents=args.n_agents,
        n_landmarks=args.n_landmarks,
        n_episodes=args.n_episodes,
        max_steps=args.max_steps,
        hidden_dim=args.hidden_dim,
        lr=args.lr,
        gamma=args.gamma,
        batch_size=args.batch_size,
        lambda_weight=args.lambda_weight,
        upload_interval=args.upload_interval,
        selfish_ratio=args.selfish_ratio,
        mode=args.mode,
        seed=args.seed,
        log_interval=args.log_interval,
        # 消融实验开关（配送主证据不用消融，保持关闭）
        ablate_security=getattr(args, "ablate_security", False),
        ablate_consensus=getattr(args, "ablate_consensus", False),
        ablate_incentive=getattr(args, "ablate_incentive", False),
        weight_broadening=getattr(args, "weight_broadening", False),
        omission_ratio=getattr(args, "omission_ratio", 0.0),
        use_shapley_incentive=getattr(args, "use_shapley_incentive", False),
        omission_seed=getattr(args, "omission_seed", 0),
        # 自适应 lambda / Nash 验证
        adaptive_lambda=not getattr(args, "no_adaptive_lambda", False),
        verify_nash=not getattr(args, "no_verify_nash", False),
        algorithm=args.algorithm,
        consensus_shaping=getattr(args, "consensus_shaping", False),
        shaping_eta=getattr(args, "shaping_eta", 0.0),
        reward_noise_sigma=getattr(args, "reward_noise_sigma", 0.0),
        betrayal_mode="greedy",  # E41: 默认理性贪心（配送 myopic 导航）
    )

    trainer = None
    stats = None

    def _graceful_shutdown(signum, frame):
        logger.info("[SIGINT] 收到中断信号，正在保存状态...")
        if trainer and stats:
            try:
                trainer.export_results(args.save)
                logger.info(f"[SIGINT] 训练结果已导出到 {args.save}")
            except Exception as e:
                logger.warning(f"[SIGINT] 导出失败: {e}")
        logger.info("[SIGINT] 安全退出")
        sys.exit(0)

    signal.signal(signal.SIGINT, _graceful_shutdown)

    logger.info(f"启动配送训练: mode={config.mode} algorithm={config.algorithm} seed={config.seed}")
    trainer = DeliveryTrainer(config)
    stats = trainer.train()
    trainer.export_results(args.save)
    logger.info(f"[Delivery] 训练完成: {args.save}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    main()

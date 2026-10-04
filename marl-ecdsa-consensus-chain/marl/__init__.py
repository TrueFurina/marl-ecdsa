"""
MARL协同层
多智能体强化学习训练框架，与区块链层双向协同

核心公式：total_reward = env_reward + λ * bc_score

子模块：
- envs/         : 训练环境（MPE simple_spread 等）
- algorithms/   : MARL算法（QMIX 等）
- integration/  : 区块链-MARL 双向桥接层
"""
from .envs import SimpleSpreadEnv
from .algorithms import QMIXAgent, QMIXMixer, QMIXTrainer
from .integration import BlockchainMARLBridge, SelfishAgentWrapper, create_agents

__all__ = [
    'SimpleSpreadEnv',
    'QMIXAgent', 'QMIXMixer', 'QMIXTrainer',
    'BlockchainMARLBridge', 'SelfishAgentWrapper', 'create_agents',
]

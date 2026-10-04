"""
异构智能体环境：能力差异构造
- agent_0: 正常能力（无噪声）
- agent_1: 正常能力
- agent_2: 低能力（30% 概率执行随机动作，模拟能力不足/故障节点）
用于验证 CW-PBFT 贡献度加权在异构场景下的价值
"""
import numpy as np
from marl.envs.simple_spread import SimpleSpreadEnv


class SimpleSpreadHeterogeneousEnv(SimpleSpreadEnv):
    """
    异构智能体环境：agent_2 有 30% 概率执行随机动作
    模拟真实分布式系统中的能力差异节点
    """

    def __init__(self, n_agents=3, n_landmarks=3, max_steps=25, weak_agent_idx=2, weak_noise_rate=0.3):
        super().__init__(n_agents, n_landmarks, max_steps=max_steps)
        self.weak_agent_idx = weak_agent_idx
        self.weak_noise_rate = weak_noise_rate
        self.noise_injected = 0  # 统计噪声注入次数

    def step(self, actions):
        """
        执行动作，对弱能力智能体注入随机动作噪声
        """
        # 对弱能力智能体注入噪声
        modified_actions = actions.copy()
        if np.random.random() < self.weak_noise_rate:
            modified_actions[self.weak_agent_idx] = np.random.randint(0, self.n_actions)
            self.noise_injected += 1

        return super().step(modified_actions)

    def reset(self):
        self.noise_injected = 0
        return super().reset()

    def get_agent_capabilities(self):
        """返回各智能体能力描述（用于日志）"""
        caps = []
        for i in range(self.n_agents):
            if i == self.weak_agent_idx:
                caps.append(f"agent_{i}: weak (noise_rate={self.weak_noise_rate})")
            else:
                caps.append(f"agent_{i}: normal")
        return caps

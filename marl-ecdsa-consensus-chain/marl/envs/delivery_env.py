"""
配送 MARL 环境 v2：骑手-无人机协同
- 固定 2 个订单，每个订单分配给一个骑手
- 骑手1(agent0)负责订单1，骑手2(agent1)负责订单2，无人机(agent2)负责跨区接力
- 订单位置固定（可复现），智能体只需学会导航
"""
import numpy as np
from typing import List


class DeliveryMARLEnv:
    PICKUP_BONUS = 1.0
    DELIVERY_BONUS = 5.0
    HANDOFF_BONUS = 2.0
    UAV_PICKUP_BONUS = 1.0
    STEP_COST = -0.02
    TIMEOUT_PENALTY = -2.0

    def __init__(self, max_steps=60):
        self.n_agents = 3
        self.n_orders = 2
        self.n_actions = 5
        self.max_steps = max_steps

        # 固定订单位置（可复现）
        # 订单1：左区近距，骑手1直送
        self.order_pickups = np.array([[0.2, 0.3], [0.8, 0.7]])
        self.order_deliveries = np.array([[0.35, 0.45], [0.65, 0.55]])
        # 交接点（中部）
        self.handoff_pos = np.array([[0.5, 0.5], [0.5, 0.5]])

        # 每个智能体的目标点（动态变化）
        # obs: 自身位置(2) + 类型(1) + 当前目标点(2) + 交接点(2) + 其他智能体位置(4)
        self.obs_dim = 2 + 1 + 2 + 2 + 4
        self.state_dim = 2 * self.n_agents + self.n_orders

        self._action_deltas = np.array([
            [0.0, 0.0], [0.0, 0.08], [0.0, -0.08], [-0.08, 0.0], [0.08, 0.0],
        ])

        self.reset()

    def reset(self):
        self.step_count = 0
        # 智能体初始位置（中心）
        self.agent_pos = np.array([[0.5, 0.5], [0.5, 0.5], [0.5, 0.5]])
        # 订单状态：0=待取, 1=已取待送, 2=在交接点, 3=无人机已取, 4=完成
        self.order_states = np.zeros(self.n_orders, dtype=int)
        self.completed = 0
        self._pending_handoff = None
        return self._get_obs()

    def _get_obs(self):
        obs = []
        for i in range(self.n_agents):
            target = self._get_target(i)
            others = []
            for k in range(self.n_agents):
                if k != i:
                    others.extend(self.agent_pos[k])
            o = np.concatenate([
                self.agent_pos[i],
                [1.0 if i < 2 else 0.0],  # 类型
                target,  # 当前目标点
                self.handoff_pos[0],  # 交接点
                others,  # 其他智能体
            ])
            obs.append(o)
        return obs

    def _get_target(self, i):
        """返回智能体 i 当前应去的目标点"""
        if i == 0:  # 骑手1 负责订单0
            s = self.order_states[0]
            if s == 0: return self.order_pickups[0]
            if s == 1: return self.order_deliveries[0]  # 直送
            return np.array([0.5, 0.5])
        if i == 1:  # 骑手2 负责订单1（跨区，送交接点）
            s = self.order_states[1]
            if s == 0: return self.order_pickups[1]
            if s == 1: return self.handoff_pos[0]  # 送交接点
            return np.array([0.5, 0.5])
        if i == 2:  # 无人机
            if self.order_states[1] == 2:
                return self.handoff_pos[0]  # 去交接点取货
            if self.order_states[1] == 3:
                return self.order_deliveries[1]  # 送终点
            return np.array([0.5, 0.5])
        return np.array([0.5, 0.5])

    def step(self, actions):
        self.step_count += 1
        rewards = np.zeros(self.n_agents)
        done = False

        # 记录移动前到目标距离
        prev_dists = np.array([np.linalg.norm(self.agent_pos[i] - self._get_target(i)) for i in range(self.n_agents)])

        # 更新位置
        for i in range(self.n_agents):
            delta = self._action_deltas[actions[i]]
            self.agent_pos[i] = np.clip(self.agent_pos[i] + delta, 0.0, 1.0)
            rewards[i] += self.STEP_COST

        # 势函数 shaping：距离减少给奖励
        new_dists = np.array([np.linalg.norm(self.agent_pos[i] - self._get_target(i)) for i in range(self.n_agents)])
        for i in range(self.n_agents):
            rewards[i] += (prev_dists[i] - new_dists[i]) * 3.0  # 靠近1单位距离+3

        # 检查交互
        self._check(rewards)

        if self.completed >= self.n_orders:
            done = True
        if self.step_count >= self.max_steps:
            done = True
            for i in range(self.n_agents):
                rewards[i] += self.TIMEOUT_PENALTY / self.n_agents

        info = {"completed": self.completed, "step": self.step_count}
        return self._get_obs(), rewards, done, info

    def _check(self, rewards):
        TH = 0.05
        # 订单0：骑手1 直送
        if self.order_states[0] == 0:
            if np.linalg.norm(self.agent_pos[0] - self.order_pickups[0]) < TH:
                self.order_states[0] = 1
                rewards[0] += self.PICKUP_BONUS
        elif self.order_states[0] == 1:
            if np.linalg.norm(self.agent_pos[0] - self.order_deliveries[0]) < TH:
                self.order_states[0] = 4
                self.completed += 1
                rewards[0] += self.DELIVERY_BONUS

        # 订单1：骑手2 取货 → 交接点 → 无人机 → 送货点
        if self.order_states[1] == 0:
            if np.linalg.norm(self.agent_pos[1] - self.order_pickups[1]) < TH:
                self.order_states[1] = 1
                rewards[1] += self.PICKUP_BONUS
        elif self.order_states[1] == 1:
            if np.linalg.norm(self.agent_pos[1] - self.handoff_pos[0]) < TH:
                self.order_states[1] = 2
                rewards[1] += self.HANDOFF_BONUS
        elif self.order_states[1] == 2:
            if np.linalg.norm(self.agent_pos[2] - self.handoff_pos[0]) < TH:
                self.order_states[1] = 3
                rewards[2] += self.UAV_PICKUP_BONUS
        elif self.order_states[1] == 3:
            if np.linalg.norm(self.agent_pos[2] - self.order_deliveries[1]) < TH:
                self.order_states[1] = 4
                self.completed += 1
                rewards[2] += self.DELIVERY_BONUS


class DeliveryAdapterEnv:
    """配送环境适配层：对齐 MARLBlockchainTrainer 接口（5 元组 step + get_state）。

    包装 DeliveryMARLEnv，不改变其原始语义（早期 train_delivery_*.py 仍消费
    4 元组 step）。补齐主训练链路（train.py 体系）所需的三项：
      - step 返回 (obs, global_rewards, local_rewards, done, info)
      - get_state()：供共识塑形/状态记录使用
      - 属性透传：n_agents / n_actions / obs_dim / state_dim / max_steps
    """

    def __init__(self, max_steps=60):
        self._inner = DeliveryMARLEnv(max_steps=max_steps)
        self.n_agents = self._inner.n_agents
        self.n_actions = self._inner.n_actions
        self.obs_dim = self._inner.obs_dim
        self.state_dim = self._inner.state_dim
        self.max_steps = self._inner.max_steps

    def reset(self):
        return self._inner.reset()

    def step(self, actions):
        obs, rewards, done, info = self._inner.step(actions)
        rewards = np.asarray(rewards, dtype=float)
        global_rewards = [float(rewards.sum())]
        local_rewards = rewards.tolist()
        return obs, global_rewards, local_rewards, done, info

    def get_state(self):
        # state_dim = 2*n_agents + n_orders = 8：位置(6) + 订单状态(2)
        return np.concatenate([
            self._inner.agent_pos.flatten(),
            self._inner.order_states.astype(float),
        ])


if __name__ == "__main__":
    env = DeliveryMARLEnv()
    print(f"obs_dim={env.obs_dim}, n_agents={env.n_agents}")
    for ep in range(3):
        obs = env.reset()
        for step in range(60):
            actions = [np.random.randint(0, 5) for _ in range(3)]
            obs, r, done, info = env.step(actions)
            if done:
                print(f"ep{ep}: completed={info['completed']}/2, steps={info['step']}")
                break

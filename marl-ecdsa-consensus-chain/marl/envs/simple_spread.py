"""
简化版 MPE simple_spread 环境封装
不依赖 openai/multiagent-particle-envs，纯NumPy自实现
用于快速验证区块链-MARL协同效果

场景：N个智能体需要覆盖N个目标点
- 每个智能体应到达指定目标点（按ID分配）
- 全局奖励 = -sum(dist(agent_i, landmark_i))
- 局部奖励 = -dist(agent_i, nearest_landmark)
"""
import numpy as np
from typing import List, Tuple, Dict, Any, Optional

class SimpleSpreadEnv:
    # 覆盖奖励常数（使学会后的奖励明显为正）
    COVERAGE_BONUS = 2.0        # 智能体覆盖任意目标点时每步获得
    # P2-11 修复：明确两个阈值的语义差异
    # COVERAGE_THRESHOLD = 环境内的覆盖判定（agent 到 landmark 距离 < 此值 = 覆盖成功）
    # cooperation_threshold (bc_integration) = 合作检测判定（agent 到任意 landmark 距离 < 此值 = 合作行为）
    # 语义关系：合作阈值 (0.5) > 覆盖阈值 (0.15)，因为"靠近"比"精确覆盖"判定更宽松
    # 合作者可能靠近 (dist<0.5) 但尚未精确覆盖 (dist>0.15)，这是正常的学习过程
    COVERAGE_THRESHOLD = 0.15   # 覆盖判定的距离阈值（精确覆盖）

    def __init__(
        self,
        n_agents: int = 3,
        n_landmarks: int = 3,
        world_size: float = 1.0,
        max_speed: float = 0.5,
        dt: float = 0.1,
        damping: float = 0.25,
        max_steps: int = 25,
    ):
        self.n_agents = n_agents
        self.n_landmarks = n_landmarks
        self.world_size = world_size
        self.max_speed = max_speed
        self.dt = dt
        self.damping = damping
        self.max_steps = max_steps

        # 状态维度
        self.obs_dim = 2 + 2 + 2 * n_landmarks + 2 * (n_agents - 1)
        # vel(2) + pos(2) + landmarks_rel(2*n_lm) + other_agents_rel(2*(n-1))
        self.n_actions = 5  # 无操作/上/下/左/右
        self.state_dim = (2 + 2) * n_agents + 2 * n_landmarks  # 全局状态

        # 动作到力的映射
        self._action_forces = np.array([
            [0.0, 0.0],   # 无操作
            [0.0, 0.5],   # 上
            [0.0, -0.5],  # 下
            [-0.5, 0.0],  # 左
            [0.5, 0.0],   # 右
        ])

        self.reset()

    def reset(self) -> List[np.ndarray]:
        """重置环境"""
        # 随机初始化智能体位置和速度
        self._agent_pos = np.random.uniform(-self.world_size, self.world_size, (self.n_agents, 2))
        self._agent_vel = np.zeros((self.n_agents, 2))
        # 随机初始化目标点位置（固定，不移动）
        self._landmark_pos = np.random.uniform(
            -self.world_size * 0.8, self.world_size * 0.8, (self.n_landmarks, 2)
        )
        self._step_count = 0
        return self._get_observations()

    def step(self, actions: List[int]) -> Tuple[List[np.ndarray], List[float], List[float], bool, Dict]:
        """
        执行一步
        :param actions: 每个智能体的离散动作（0-4）
        :return: (observations, global_rewards, local_rewards, done, info)
        """
        self._step_count += 1

        # 更新智能体位置
        for i, action in enumerate(actions):
            a = int(action) if action is not None else 0
            force = self._action_forces[a % self.n_actions]
            # 欧拉积分：速度+=力*dt，位置+=速度*dt
            self._agent_vel[i] = (self._agent_vel[i] + force) * (1 - self.damping)
            # 限制速度
            speed = np.linalg.norm(self._agent_vel[i])
            if speed > self.max_speed:
                self._agent_vel[i] = self._agent_vel[i] / speed * self.max_speed
            self._agent_pos[i] += self._agent_vel[i] * self.dt
            # 边界处理
            self._agent_pos[i] = np.clip(self._agent_pos[i], -self.world_size, self.world_size)

        # 计算奖励
        global_rewards, local_rewards = self._compute_rewards()

        # 判断结束条件（最大步数 or 所有目标被覆盖）
        done = self._step_count >= self.max_steps
        coverage = self._check_coverage()
        if coverage:
            done = True

        info = {
            'coverage': coverage,
            'step': self._step_count,
            'agent_positions': self._agent_pos.copy(),
            'landmark_positions': self._landmark_pos.copy(),
        }

        return self._get_observations(), global_rewards, local_rewards, done, info

    def _compute_rewards(self) -> Tuple[List[float], List[float]]:
        """
        计算奖励
        全局奖励：-sum(min_dist(landmark_j, any_agent))（覆盖奖励）
        局部奖励：-dist(agent_i, nearest_landmark)（个人最近目标）
        """
        global_rewards = []
        local_rewards = []

        # 全局奖励：每个目标点到最近智能体的距离之和（负值）
        global_penalty = 0.0
        for j in range(self.n_landmarks):
            dists = [np.linalg.norm(self._agent_pos[i] - self._landmark_pos[j])
                     for i in range(self.n_agents)]
            global_penalty -= min(dists)

        for i in range(self.n_agents):
            global_rewards.append(global_penalty)

            # 局部奖励：到自己分配目标点的距离 + 覆盖任意目标点的 bonus
            own_landmark_idx = i % self.n_landmarks
            local_dist = -np.linalg.norm(self._agent_pos[i] - self._landmark_pos[own_landmark_idx])
            
            # 覆盖奖励：当智能体靠近任意目标点时给予正向 bonus
            min_dist_any = min([
                np.linalg.norm(self._agent_pos[i] - self._landmark_pos[j])
                for j in range(self.n_landmarks)
            ])
            coverage_bonus = self.COVERAGE_BONUS if min_dist_any < self.COVERAGE_THRESHOLD else 0.0
            local_rewards.append(local_dist + coverage_bonus)

        return global_rewards, local_rewards

    def _check_coverage(self, threshold: float = None) -> bool:
        """检查所有目标点是否被覆盖"""
        if threshold is None:
            threshold = self.COVERAGE_THRESHOLD
        for j in range(self.n_landmarks):
            covered = any(
                np.linalg.norm(self._agent_pos[i] - self._landmark_pos[j]) < threshold
                for i in range(self.n_agents)
            )
            if not covered:
                return False
        return True

    def _get_observations(self) -> List[np.ndarray]:
        """构造每个智能体的局部观测"""
        observations = []
        for i in range(self.n_agents):
            obs = [
                self._agent_vel[i],                                   # 自身速度 (2)
                self._agent_pos[i],                                   # 自身位置 (2)
            ]
            # 所有目标点的相对位置 (2*n_lm)
            for j in range(self.n_landmarks):
                obs.append(self._landmark_pos[j] - self._agent_pos[i])
            # 其他智能体的相对位置 (2*(n-1))
            for k in range(self.n_agents):
                if k != i:
                    obs.append(self._agent_pos[k] - self._agent_pos[i])

            observations.append(np.concatenate(obs))
        return observations

    def get_state(self) -> np.ndarray:
        """获取全局状态（用于QMIX混合网络）"""
        state = [
            self._agent_pos.flatten(),
            self._agent_vel.flatten(),
            self._landmark_pos.flatten(),
        ]
        return np.concatenate(state)

    def render_text(self) -> str:
        """文本形式展示当前状态"""
        lines = [f"回合步数: {self._step_count}"]
        for i in range(self.n_agents):
            pos = self._agent_pos[i]
            own_lm = self._landmark_pos[i % self.n_landmarks]
            dist = np.linalg.norm(pos - own_lm)
            lines.append(f"  agent_{i}: pos=({pos[0]:.3f},{pos[1]:.3f}) dist_to_own={dist:.3f}")
        for j in range(self.n_landmarks):
            lm = self._landmark_pos[j]
            lines.append(f"  landmark_{j}: pos=({lm[0]:.3f},{lm[1]:.3f})")
        return "\n".join(lines)

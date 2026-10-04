"""
第二个环境：动态目标变体（SimpleSpreadMovingEnv）。

设计目标（任务 A｜环境多样性扩展）：
- 在 SimpleSpread 基础上让地标（目标点）缓慢漂移，构成一个**非平稳**（non-stationary）
  协作覆盖任务，作为支撑"泛化性"论证的第二个环境。
- **严格复用同一 obs/state/action 接口与维度布局**（vel2 + pos2 + landmarks_rel(2*n_lm)
  + other_agents_rel(2*(n-1))），因此 train.py 中的 BC 集成（合作检测、激励结算、
  纯 MARL 合作率统计）无需任何改动即可直接生效 —— 满足"本地只新增脚本、不改现有文件"。

漂移机制（确定性、可复现）：
- 每个地标带一个固定方向的小速度向量，按步长推进；触界则反射，保证始终在 world 内。
- 速度幅度由 landmark_speed 控制（默认 0.04，远小于智能体 max_speed=0.5，保证任务可学习）。
"""
import numpy as np

from marl.envs.simple_spread import SimpleSpreadEnv


class SimpleSpreadMovingEnv(SimpleSpreadEnv):
    def __init__(
        self,
        n_agents: int = 3,
        n_landmarks: int = 3,
        world_size: float = 1.0,
        max_speed: float = 0.5,
        dt: float = 0.1,
        damping: float = 0.25,
        max_steps: int = 25,
        landmark_speed: float = 0.04,
        seed: int = None,
    ):
        self._landmark_speed = float(landmark_speed)
        self._rng = np.random.RandomState(seed)
        # 先在父类 __init__ 里完成普通 SimpleSpread 的初始化（含静态地标）
        super().__init__(
            n_agents=n_agents, n_landmarks=n_landmarks, world_size=world_size,
            max_speed=max_speed, dt=dt, damping=damping, max_steps=max_steps,
        )

    def reset(self):
        obs = super().reset()  # 父类已设置 _agent_pos/_agent_vel/_landmark_pos/_step_count=0
        # 为漂移地标初始化固定速度方向（确定性，依赖 seed）
        self._landmark_vel = self._rng.uniform(
            -self._landmark_speed, self._landmark_speed, (self.n_landmarks, 2)
        )
        return obs

    def step(self, actions):
        # 先把地标推进一小步（触界反射），再交给父类按新地标位置计算奖励/观测/覆盖
        self._landmark_pos = np.clip(
            self._landmark_pos + self._landmark_vel,
            -self.world_size, self.world_size,
        )
        hit_low = self._landmark_pos <= -self.world_size
        hit_high = self._landmark_pos >= self.world_size
        self._landmark_vel[hit_low | hit_high] *= -1.0
        return super().step(actions)

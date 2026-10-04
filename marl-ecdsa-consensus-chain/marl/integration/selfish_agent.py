"""
自私智能体封装
用于模拟自私/背叛行为，测试区块链激励机制的抗干扰能力
"""
import logging
import random
from typing import Any, Optional

logger = logging.getLogger(__name__)

# greedy 一步贪心的**校准**每步位移（按 SimpleSpreadEnv 动力学实测）：
#   v ← (v + f)·(1 - damping)；pos ← v·dt，dt=0.1、damping=0.25、|f|=0.5、max_speed=0.5
#   → 静止起步 0.0375，稳态 0.05（速度被 max_speed 裁剪后固定为 0.5·0.1）
# 历史默认值为 0.5（力的量级，非位移），保留在 SelfishAgentWrapper.greedy_step 默认值中。
GREEDY_STEP_CALIBRATED = 0.05


class SelfishAgentWrapper:
    """
    自私智能体封装器
    包装任意MARL智能体，通过开关控制自私行为模式
    
    自私模式：
    - 只考虑自身局部奖励，忽略全局协作目标
    - betrayal_mode='greedy'：理性自私——每步朝**最近**路标做一步贪心移动
      （局部观测可实现的最优：最大化覆盖 bonus 这一局部奖励主导项。
       注：分配路标下标不在观测里；本环境无拥挤惩罚，故不存在"挤占他人"的收益。
       详见 _greedy_action 的 docstring）
    - betrayal_mode='random'：以随机概率换成随机动作（旧行为，作对照）
    - 用于对照实验：测试不同自私比例下区块链激励的效果
    """

    def __init__(
        self,
        agent_id: str,
        base_agent,                    # 底层MARL智能体
        is_selfish: bool = False,      # 是否为自私模式
        betrayal_prob: float = 0.3,    # 自私模式下的背叛概率（random 模式用）
        n_actions: int = 5,            # 动作空间大小（用于背叛时选择随机动作）
        n_landmarks: int = 3,          # 路标数（greedy 模式解析观测用）
        betrayal_mode: str = 'random', # 'greedy'=理性自私 | 'random'=随机背叛（默认，保持旧行为）
        greedy_step: float = 0.5,      # greedy 一步贪心假设的每步位移（默认沿用历史值）
    ):
        self.agent_id = agent_id
        self.base_agent = base_agent
        self.is_selfish = is_selfish
        self.betrayal_prob = betrayal_prob
        self.n_actions = n_actions
        self.n_landmarks = n_landmarks
        self.betrayal_mode = betrayal_mode
        self.greedy_step = float(greedy_step)
        self._betrayal_count = 0
        self._total_steps = 0

    # 观测布局（SimpleSpreadEnv._get_observations）：
    #   [0:2] 自身速度 | [2:4] 自身位置 | [4:4+2*n_lm] 各路标相对位置 | 其余他者相对位置
    def _greedy_action(self, obs) -> int:
        """理性自私：朝**最近**路标移动的一步贪心（myopic 1-step planner）。

        ⚠️ 2026-09-22 校准：本方法的 docstring 曾与其实现不符，现按**实际实现**重写。
        论文/报告描述必须以下面"实际做的事"为准，不得沿用旧表述。

        实际做的事
        ----------
        1. 从局部观测解析全部路标的相对位置（obs[4 : 4+2*n_landmarks]）；
        2. 选**欧氏距离最近**的那个路标；
        3. 在 5 个离散动作中，选使"到该路标的曼哈顿距离"下降最多的动作。

        为什么是"最近路标"而不是"分配路标"
        --------------------------------
        环境的局部奖励为（见 SimpleSpreadEnv._compute_rewards）：
            local_reward = -dist(自己, 分配路标 j=i%n_landmarks) + COVERAGE_BONUS·1[min_dist_any < 0.15]
        但**分配路标下标 j 只由智能体编号 i 决定，而 i 不在局部观测里**
        （观测 = [自身速度, 自身位置, 各路标相对位置, 他者相对位置]，无智能体编号）。
        因此从局部观测出发，**"去最近路标"是唯一可实现的一步贪心**——它恰好最大化
        覆盖 bonus（离散大项 2.0），也是局部奖励的主导项。这是可识别性限制，不是实现疏漏。

        关于"挤占他人目标点"（旧 docstring 的说法，已撤回）
        ------------------------------------------------
        本环境**没有碰撞/拥挤惩罚**（_compute_rewards 中无此项），
        一个自利智能体挤占他人目标点对自己**没有任何收益**。
        所以"挤占他人"既未实现，也不构成理性自私的合理建模目标。该表述已删除。

        已知近似（写入 limitation，不作为 bug 修复）
        ------------------------------------------
        候选评分用的步长 `self.greedy_step`，默认 **0.5 是历史遗留值**（它其实是
        _action_forces 的力的量级，不是位移）。实测环境每步位移：
            v ← (v + f)·(1 - damping)；pos ← v·dt
        静止起步 ≈ 0.0375，稳态 ≈ 0.05（受 max_speed=0.5 裁剪）→ 见 GREEDY_STEP_CALIBRATED。
        因此默认死区约为 ±0.25/轴，比真实步长大一个数量级。
        方向选择（上下左右谁更优）对任意正步长都不变，故**排序结论稳健**；
        但默认设置下智能体会停在距最近路标约 0.2~0.25 处，达不到 COVERAGE_THRESHOLD=0.15。
        步长现可通过 `greedy_step` 参数切换：默认 0.5 保持历史行为可复现，
        0.05（= GREEDY_STEP_CALIBRATED）为按环境动力学校准后的值。
        修正会改变已有实验行为（E13/E14 需重跑），故本轮只更正文档、保留行为。

        动作映射（已逐条核对 SimpleSpreadEnv._action_forces，方向正确）：
        0=无操作 1=上(+y) 2=下(-y) 3=左(-x) 4=右(+x)。
        """
        import numpy as np
        start = 4
        best_a, best_d = 0, None
        # 找最近路标
        lm = obs[start:start + 2 * self.n_landmarks]
        nearest = None
        for j in range(self.n_landmarks):
            dx, dy = float(lm[2 * j]), float(lm[2 * j + 1])
            d = dx * dx + dy * dy
            if nearest is None or d < nearest[0]:
                nearest = (d, dx, dy)
        if nearest is None:
            return 0
        _, dx, dy = nearest
        # 选择使靠近最近路标最快的动作（力方向：1=+y 2=-y 3=-x 4=+x）
        s = self.greedy_step
        candidates = [
            (0, abs(dx) + abs(dy)),                     # 无操作
            (1, abs(dx) + abs(dy - s)),                 # 上：dy 减小 s
            (2, abs(dx) + abs(dy + s)),                 # 下：dy 增大 s
            (3, abs(dx + s) + abs(dy)),                 # 左：dx 增大 s
            (4, abs(dx - s) + abs(dy)),                 # 右：dx 减小 s
        ]
        return min(candidates, key=lambda t: t[1])[0]

    def get_reward(self, global_reward: float, local_reward: float) -> float:
        """
        获取智能体使用的奖励信号
        - 诚实智能体：使用全局奖励（激励合作）
        - 自私智能体：仅使用局部奖励（激励自私）
        """
        if self.is_selfish:
            return local_reward
        return global_reward

    def should_betray(self) -> bool:
        """
        判断当前步是否采取背叛行为
        仅在自私模式下有效；greedy 模式每步都背叛（理性逐利），random 模式按概率
        """
        if not self.is_selfish:
            return False
        if self.betrayal_mode == 'greedy':
            return True
        return random.random() < self.betrayal_prob

    def step(self, obs, hidden_state=None):
        """
        执行一步决策
        - 诚实模式：正常调用底层智能体
        - 自私-greedy：直接执行贪心动作（不查询底层策略）
        - 自私-random：有概率替换为随机动作
        """
        self._total_steps += 1
        betrayed = self.should_betray()

        if self.is_selfish and self.betrayal_mode == 'greedy' and betrayed:
            self._betrayal_count += 1
            if obs is None:
                # 防御回退：无观测时退化为底层策略/默认动作
                action, new_hidden = self.base_agent.get_action(None, hidden_state) if hasattr(
                    self.base_agent, 'get_action') else (0, hidden_state)
                return action, new_hidden
            action = self._greedy_action(obs)
            logger.debug(f"[SelfishAgent] {self.agent_id} 贪心背叛(action={action})，累计{self._betrayal_count}次")
            return action, hidden_state

        action, new_hidden = self.base_agent.get_action(obs, hidden_state) if hasattr(
            self.base_agent, 'get_action') else (0, hidden_state)

        if betrayed:
            self._betrayal_count += 1
            # P1-3 修复：背叛时真正替换为随机动作（可能挤占他人目标点）
            action = random.randint(0, self.n_actions - 1)
            logger.debug(f"[SelfishAgent] {self.agent_id} 执行背叛动作(action={action})，累计背叛{self._betrayal_count}次")

        return action, new_hidden

    def get_stats(self) -> dict:
        betrayal_rate = self._betrayal_count / max(1, self._total_steps)
        return {
            'agent_id': self.agent_id,
            'is_selfish': self.is_selfish,
            'betrayal_count': self._betrayal_count,
            'total_steps': self._total_steps,
            'betrayal_rate': betrayal_rate,
        }


def create_agents(
    n_agents: int,
    selfish_ratio: float = 0.0,
    base_agent_class=None,
    agent_kwargs: Optional[dict] = None
) -> list:
    """
    批量创建智能体列表
    :param n_agents: 智能体总数
    :param selfish_ratio: 自私智能体比例（0.0-1.0）
    :param base_agent_class: 底层MARL智能体类
    :param agent_kwargs: 底层智能体初始化参数
    :return: SelfishAgentWrapper 列表
    """
    agent_kwargs = agent_kwargs or {}
    n_selfish = max(1, round(n_agents * selfish_ratio)) if selfish_ratio > 0 else 0
    agents = []

    for i in range(n_agents):
        agent_id = f"agent_{i}"
        is_selfish = i < n_selfish

        if base_agent_class is not None:
            base = base_agent_class(agent_id=agent_id, **agent_kwargs)
        else:
            base = None

        wrapper = SelfishAgentWrapper(
            agent_id=agent_id,
            base_agent=base,
            is_selfish=is_selfish,
            betrayal_prob=0.3 if is_selfish else 0.0,
        )
        agents.append(wrapper)

        if is_selfish:
            logger.info(f"[AgentFactory] 创建自私智能体: {agent_id}")

    logger.info(
        f"[AgentFactory] 共创建 {n_agents} 个智能体，"
        f"其中 {n_selfish} 个自私（比例={selfish_ratio:.1%}）"
    )
    return agents

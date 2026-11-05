"""
CARS共识感知奖励塑形（Consensus-Aware Reward Shaping）

在每一步训练中注入共识反馈信号，将区块链共识状态映射为稠密的奖励信号。
与原有回合末结算（settlement）互补，形成 BC→MARL 的双向逐步反馈。

核心公式:
    final_reward_i[t] = env_reward_i[t] 
                        + lambda * settlement_delta_i / T 
                        + eta * shaping_i[t]

shaping_i[t] 由三个分量组成:
    1. verification_bonus: 动作被ECDSA签名+SecurityGuard验证通过
    2. cooperation_bonus:  动作与合作模式对齐（接近分配的路标）
    3. consensus_bonus:    与CW-PBFT贡献权重成正比

设计原则:
    - 核心塑形项采用Potential-based设计(F = γΦ(s') - Φ(s))，保证最优策略不变性
    - 额外bonus项（verification_bonus、cooperation_bonus、consensus_weight_scale）
      不满足potential-based条件，构成近似偏移。定量分析：bonus总量≤η*0.18≈0.009，
      相对主奖励信号偏移率<1%，对最优策略的影响在可接受范围内
    
    声明：**近似策略不变性**（非严格不变性），偏移量有界且可控
    - eta 控制塑形强度，默认0.05（弱于lambda，避免主导学习信号）
"""
import logging
import math
from typing import Dict, List, Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)


def _finite_or_none(value) -> Optional[float]:
    """有限 float 或 None（NaN/±inf/不可转换 一律 None）。

    2026-11-05 修复：共识权重与贡献分此前不做任何值域检查。实测
    ``consensus_weights={'agent_0': nan}`` 会让**塑形奖励本身**变成 NaN
    （`inf` 同理），而塑形奖励直接加在 env_reward 上进入训练 —— 单步 NaN
    奖励足以让整批策略梯度变成 NaN，且不回滚。统计侧更糟：`inf` 权重让
    `total_consensus_bonus` 永久变 inf，`get_stats()` 之后永远报 inf。

    处置与 §9 一致：非有限值按"无信号"处理（不加不扣），不钳成上界。
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


class ConsensusRewardShaper:
    """
    CARS共识感知奖励塑形器
    
    核心塑形项采用Potential-based设计(F = γΦ(s') - Φ(s))，保证最优策略不变性。
    额外bonus项（verification_bonus、cooperation_bonus、consensus_weight_scale）不满足
    potential-based条件，构成近似偏移。定量分析：bonus总量≤η*0.18≈0.009，
    相对主奖励信号偏移率<1%，对最优策略的影响在可接受范围内。
    
    声明：**近似策略不变性**（非严格不变性），偏移量有界且可控。
    
    每步调用 shape_reward()，根据共识状态返回塑形奖励向量。
    塑形奖励叠加到环境奖励之上，为MARL智能体提供稠密的共识反馈。
    """

    def __init__(
        self,
        n_agents: int = 3,
        eta: float = 0.05,
        gamma: float = 0.8,
        verification_bonus: float = 0.10,
        cooperation_bonus: float = 0.08,
        consensus_weight_scale: float = 0.05,
        n_landmarks: int = 3,
    ):
        """
        :param n_agents: 智能体数量
        :param eta: 塑形强度系数（控制总塑形奖励的幅度）
        :param gamma: 折扣因子（用于potential-based shaping）
        :param verification_bonus: 验证通过的单步奖励
        :param cooperation_bonus: 合作对齐的单步奖励
        :param consensus_weight_scale: 共识权重奖励的缩放因子
        :param n_landmarks: 路标数量（用于合作检测）
        """
        self.n_agents = n_agents
        self.eta = eta
        self.gamma = gamma
        self.verification_bonus = verification_bonus
        self.cooperation_bonus = cooperation_bonus
        self.consensus_weight_scale = consensus_weight_scale
        self.n_landmarks = n_landmarks

        # Potential function: 基于智能体贡献分数的状态势能
        # Phi(s) = avg_contribution_score / max_possible_score
        self._prev_potentials: List[float] = [0.0] * n_agents

        # 统计
        self._step_count = 0
        self._total_verification_bonus = 0.0
        self._total_cooperation_bonus = 0.0
        self._total_consensus_bonus = 0.0
        # 2026-11-05：势能项（potential-based）分量此前完全没被累计，
        # 导致 get_stats() 的 "avg_shaping_per_step" 既不包含势能项、
        # 又用 η 之前的原始分量求和 —— 实测高报 20 倍（η=0.05）。
        self._total_potential_shaping = 0.0

    def _compute_potential(
        self,
        observations: List[np.ndarray],
        contribution_scores: Optional[Dict[str, float]] = None,
        agent_ids: Optional[List[str]] = None,
    ) -> List[float]:
        """
        计算每个智能体的势能 Phi(s)

        势能基于两个信号:
        1. 空间势能：智能体到**自己分配路标**的负距离（与环境奖励方向一致）
        2. 贡献势能：链上贡献分数（越高势能越高）

        v4.1 修复：将空间势能从"到最近路标的距离"改为"到分配路标的距离"，
        消除与 env_reward（-dist_to_own）的系统性冲突。
        原设计使用 min_dist 导致智能体靠近其他路标反而获得正塑形，
        而 env_reward 同时惩罚这一行为，形成对抗信号。

        Potential-based shaping 的策略不变性保证:
        F(s, s') = gamma * Phi(s') - Phi(s)
        此项严格满足potential-based条件，最优策略不变。
        """
        potentials = []
        for i in range(self.n_agents):
            # 空间势能：到分配路标的负距离（与环境奖励对齐）
            spatial_potential = 0.0
            try:
                obs = np.array(observations[i], dtype=float)
                # 路标相对位置在 obs[4:4+2*n_landmarks]
                lm_start = 4
                lm_end = lm_start + 2 * self.n_landmarks
                if lm_end <= len(obs):
                    lm_rel = obs[lm_start:lm_end].reshape(-1, 2)
                    own_idx = i % self.n_landmarks
                    dist_to_own = float(np.linalg.norm(lm_rel[own_idx]))
                    spatial_potential = -dist_to_own  # 越近越大，与环境奖励一致
            except (ValueError, IndexError, TypeError):
                pass

            # 贡献势能：链上贡献分数
            contribution_potential = 0.0
            if contribution_scores and agent_ids:
                aid = agent_ids[i]
                score = _finite_or_none(contribution_scores.get(aid, 0.0))
                if score is None:
                    logger.warning(
                        "[Shaper] %s 的贡献分非有限值 %r，按无信号处理",
                        aid, contribution_scores.get(aid),
                    )
                    score = 0.0
                contribution_potential = score / 15.0  # 归一化（max reward=15）

            # 加权组合（降低空间势能权重，提高贡献势能权重，减少震荡）
            phi = 0.5 * spatial_potential + 0.5 * contribution_potential
            potentials.append(phi)

        return potentials

    def _detect_cooperation(
        self,
        observations: List[np.ndarray],
        actions: List[int],
        cooperation_threshold: float = 0.5,
    ) -> List[bool]:
        """
        检测每个智能体是否采取合作行为
        合作定义：智能体接近其分配的路标（距离 < threshold）
        """
        coop_flags = []
        for i in range(self.n_agents):
            is_coop = False
            try:
                obs = np.array(observations[i], dtype=float)
                lm_start = 4
                lm_end = lm_start + 2 * self.n_landmarks
                if lm_end <= len(obs):
                    lm_rel = obs[lm_start:lm_end].reshape(-1, 2)
                    min_dist = min(float(np.linalg.norm(lm_rel[j])) for j in range(len(lm_rel)))
                    is_coop = min_dist < cooperation_threshold
            except (ValueError, IndexError, TypeError):
                pass
            coop_flags.append(is_coop)
        return coop_flags

    def shape_reward(
        self,
        observations: List[np.ndarray],
        next_observations: List[np.ndarray],
        actions: List[int],
        agent_ids: List[str],
        verification_status: Optional[List[bool]] = None,
        cooperation_status: Optional[Dict[str, bool]] = None,
        contribution_scores: Optional[Dict[str, float]] = None,
        consensus_weights: Optional[Dict[str, float]] = None,
    ) -> List[float]:
        """
        计算每个智能体的塑形奖励
        
        :param observations: 当前步观测列表
        :param next_observations: 下一步观测列表
        :param actions: 每个智能体的动作
        :param agent_ids: 智能体ID列表
        :param verification_status: 每个智能体的签名验证状态（True=通过）
        :param cooperation_status: Bridge检测的合作状态 {agent_id: bool}
        :param contribution_scores: 链上贡献分数 {agent_id: float}
        :param consensus_weights: CW-PBFT共识权重 {agent_id: float}
        :return: 每个智能体的塑形奖励列表
        """
        self._step_count += 1
        shaping = [0.0] * self.n_agents

        # 1. Potential-based shaping (严格满足potential-based条件，策略不变性保证)
        curr_potentials = self._compute_potential(observations, contribution_scores, agent_ids)
        next_potentials = self._compute_potential(next_observations, contribution_scores, agent_ids)

        pb_total = 0.0
        for i in range(self.n_agents):
            pb_shaping = self.gamma * next_potentials[i] - curr_potentials[i]
            shaping[i] += pb_shaping
            pb_total += pb_shaping

        # 2. 验证奖励：动作被ECDSA签名+SecurityGuard验证通过
        if verification_status is not None:
            for i in range(self.n_agents):
                if i < len(verification_status) and verification_status[i]:
                    shaping[i] += self.verification_bonus
                    self._total_verification_bonus += self.eta * self.verification_bonus

        # 3. 合作对齐奖励：动作与合作模式对齐
        coop_flags = self._detect_cooperation(observations, actions)
        if cooperation_status is not None:
            # 使用Bridge的检测结果（更权威）
            for i, aid in enumerate(agent_ids):
                if i < self.n_agents and cooperation_status.get(aid, False):
                    shaping[i] += self.cooperation_bonus
                    self._total_cooperation_bonus += self.eta * self.cooperation_bonus
        else:
            for i in range(self.n_agents):
                if coop_flags[i]:
                    shaping[i] += self.cooperation_bonus
                    self._total_cooperation_bonus += self.eta * self.cooperation_bonus

        # 4. 共识权重奖励：与CW-PBFT贡献权重成正比
        if consensus_weights is not None:
            neutral = 1.0 / self.n_agents
            for i, aid in enumerate(agent_ids):
                if i < self.n_agents:
                    weight = _finite_or_none(consensus_weights.get(aid, neutral))
                    if weight is None:
                        # 非有限权重按"与均值持平"处理 → bonus 恰为 0，
                        # 既不奖励也不惩罚，绝不让 NaN/inf 进入奖励向量。
                        logger.warning(
                            "[Shaper] %s 的共识权重非有限值 %r，按中性权重处理",
                            aid, consensus_weights.get(aid),
                        )
                        weight = neutral
                    # 归一化权重：weight ∈ (0, 1]，bonus = scale * (weight - 1/n)
                    # 高于平均权重的智能体获得正奖励，低于的获得负奖励
                    normalized = weight - neutral
                    bonus = self.consensus_weight_scale * normalized
                    shaping[i] += bonus
                    self._total_consensus_bonus += self.eta * bonus

        # 5. 应用eta缩放
        shaping = [self.eta * s for s in shaping]
        self._total_potential_shaping += self.eta * pb_total

        # 5.5 出口兜底：塑形奖励会直接加到 env_reward 上进入训练，非有限值
        # 必须挡在这里。上面已对权重/贡献分做了入境检查，但观测本身若含 NaN，
        # `np.linalg.norm` 会把 NaN 带进空间势能——这条路径无法在入境处覆盖。
        # 处置：该分量记 0（无塑形信号）并告警，绝不让 NaN/inf 进入梯度。
        for i, v in enumerate(shaping):
            if not math.isfinite(v):
                logger.warning(
                    "[Shaper] 第 %d 号智能体塑形奖励非有限值 %r，置 0（请检查观测/权重是否含 NaN）",
                    i, v,
                )
                shaping[i] = 0.0

        # 更新势能历史
        self._prev_potentials = next_potentials

        return shaping

    def get_stats(self) -> Dict:
        """获取塑形统计信息

        口径（2026-11-05 修正）：四个 ``total_*`` 与 ``avg_shaping_per_step``
        统计的都是**实际加进奖励里**的量，即已经乘过 η 的数值。
        修正前累计的是 η 之前的原始分量、且完全不含势能项，而字段名写的是
        "每步塑形"——实测 η=0.05 时 `avg_shaping_per_step` 比真实均值高 20 倍
        （0.18 vs 0.009）。该字段经 `train.py` 的 `shaping_stats` /
        `consensus_shaping_stats` 导出到训练结果，属对外口径，故按实测值修正。
        """
        applied_total = (
            self._total_potential_shaping
            + self._total_verification_bonus
            + self._total_cooperation_bonus
            + self._total_consensus_bonus
        )
        return {
            'step_count': self._step_count,
            'total_potential_shaping': round(self._total_potential_shaping, 6),
            'total_verification_bonus': round(self._total_verification_bonus, 6),
            'total_cooperation_bonus': round(self._total_cooperation_bonus, 6),
            'total_consensus_bonus': round(self._total_consensus_bonus, 6),
            'eta': self.eta,
            # 每步每智能体的平均塑形（含势能项与三个 bonus，均为 η 之后）
            'avg_shaping_per_step': round(
                applied_total / max(1, self._step_count * self.n_agents), 6
            ),
        }

    def reset(self):
        """重置塑形器状态（每个新回合开始时调用）"""
        self._prev_potentials = [0.0] * self.n_agents

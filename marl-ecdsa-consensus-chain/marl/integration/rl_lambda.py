"""
RL-λ 元学习调度器（增量创新 #5，启发自 EquiChain A2C-PBFT）
================================================================
在 AdaptiveLambdaController（sigmoid 比例控制器）基础上，引入轻量
"元学习"能力：用上下文 bandit / REINFORCE 风格在线学习，根据近期
训练回报自适应调整 λ 的采样分布，替代固定的 sigmoid 映射。

设计要点：
- 接口与 AdaptiveLambdaController 完全兼容（compute_adaptive_lambda /
  get_adaptation_history / get_stats / reset），可无缝替换
- 轻量实现：无需额外深度 RL 依赖（仅 numpy），适合竞赛可复现
- 元学习机制：维护 λ 候选桶的「累积回报 + 访问次数」，用 ε-greedy
  探索 + 指数加权回报更新，实现「学到如何调 λ」
- 回报信号：训练平均奖励的改善量（Δreward），与 BC-MARL 目标一致

用法：
    from marl.integration.rl_lambda import RLLambdaScheduler
    scheduler = RLLambdaScheduler(lambda_base=0.1)
    lam = scheduler.compute_adaptive_lambda(bridge_stats, episode_reward=...)
"""
import logging
import math
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


def _finite_or_none(value) -> Optional[float]:
    """有限 float 或 None（NaN/±inf/不可转换 → None）。

    2026-11-05 修复记录（同批修复，两处独立的 NaN 通道）：
    1. 指标侧：``_composite_metric`` 把 NaN 原样返回，``select_lambda_by_metric``
       里的 ``np.clip`` **不拦 NaN**（clip 只做 min/max 比较，NaN 比较恒 False
       会原样穿透），于是 λ 直接返回 NaN。
    2. 回报侧（更严重）：``episode_reward=NaN`` 经 EMA 写进 ``_bucket_rewards``
       后，``np.argmax`` 在含 NaN 的数组上会**返回 NaN 的下标**，该桶的估值
       又永远是 NaN。实测：单次 NaN 回报之后，ε=0 的 20 个回合 100% 选同一个
       桶、其余桶估值停在 0 —— 元学习器被一次 NaN 永久锁死，探索能力归零。
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _clamp_unit(value: float) -> float:
    """把比率裁剪到 [0, 1]（文档声明的值域）。"""
    return 0.0 if value < 0.0 else (1.0 if value > 1.0 else value)


# 综合指标中的 Shapley 风格权重（与 cw_pbft / AdaptiveLambdaController 的 κ_c/κ_k/κ_s 口径一致）
# 共识成功率 / 合作率 / 安全通过率 的加权系数，三者之和 = 1
COMPOSITE_W_CONSENSUS = 0.40
COMPOSITE_W_COOP = 0.35
COMPOSITE_W_SECURITY = 0.25
# 综合指标归一化区间：[COMPOSITE_NORM_MIN, COMPOSITE_NORM_MIN + COMPOSITE_NORM_SPAN] → [0, 1]
COMPOSITE_NORM_MIN = 0.3
COMPOSITE_NORM_SPAN = 0.4


class RLLambdaScheduler:
    """
    RL-λ 元学习调度器

    核心机制（上下文 bandit + 元学习）：
    1. 将 λ 空间离散为 N 个候选桶（λ_candidates）
    2. 每个 episode：按当前选择概率（softmax 于回报估计）采样一个 λ 桶
    3. 用训练回报增量 Δreward 作为 reward，指数加权更新该桶的回报估计
    4. 概率随回报估计自适应：回报高的 λ 桶被更大概率选中（元学习）
    """

    def __init__(
        self,
        lambda_base: float = 0.1,
        lambda_min: Optional[float] = None,
        lambda_max: Optional[float] = None,
        n_buckets: int = 9,
        epsilon: float = 0.15,
        reward_alpha: float = 0.3,
        initial_reward: float = 0.0,
    ):
        """
        :param lambda_base: λ 基准值
        :param lambda_min/max: λ 候选范围（默认 [0.5*base, 1.5*base]）
        :param n_buckets: λ 候选桶数量（元学习粒度）
        :param epsilon: ε-greedy 探索概率
        :param reward_alpha: 回报估计指数加权系数（0.3 = 较快适应）
        :param initial_reward: 各桶初始回报估计
        """
        self.lambda_base = float(lambda_base)
        self.lambda_min = float(lambda_min) if lambda_min is not None else 0.5 * self.lambda_base
        self.lambda_max = float(lambda_max) if lambda_max is not None else 1.5 * self.lambda_base
        self.n_buckets = max(3, int(n_buckets))
        self.epsilon = float(epsilon)
        self.reward_alpha = float(reward_alpha)

        # λ 候选桶（均匀离散）
        self.lambda_candidates: List[float] = list(
            np.linspace(self.lambda_min, self.lambda_max, self.n_buckets)
        )

        # 每个桶的回报估计与访问次数（元学习状态）
        self._bucket_rewards: np.ndarray = np.full(self.n_buckets, float(initial_reward))
        self._bucket_counts: np.ndarray = np.zeros(self.n_buckets, dtype=int)

        # 当前采样 λ 与上一回合回报（用于 Δreward 计算）
        self._current_lambda: float = self.lambda_base
        self._last_reward: Optional[float] = None

        # 历史记录（供 Dashboard 可视化）
        self._history: List[Dict] = []

        # 累计统计
        self._total_updates: int = 0

    # ----------------------------------------------------------------------
    # 主入口（与 AdaptiveLambdaController 兼容）
    # ----------------------------------------------------------------------

    def compute_adaptive_lambda(
        self,
        bridge_stats: Dict,
        episode_reward: Optional[float] = None,
    ) -> float:
        """
        计算本回合的 λ（元学习采样）

        :param bridge_stats: BlockchainMARLBridge.get_stats() 返回的统计字典
            （用于特征提取；元学习模式下主要依赖回报信号）
        :param episode_reward: 本回合训练奖励（用于 Δreward 回报更新）
        :return: 采样后的 λ 值
        """
        # 1. 用回报信号更新上一轮选中桶的回报估计（元学习）
        # 非有限回报（NaN/±inf）不参与元学习：既不做 Δreward 更新、也不更新
        # 基线。否则一次 NaN 会经 EMA 写进桶估值，并被 np.argmax 永久选中
        # （实测：此后 ε=0 的 20 回合 100% 锁在同一桶）。
        reward = None if episode_reward is None else _finite_or_none(episode_reward)
        if episode_reward is not None and reward is None:
            logger.warning(
                "[RLLambda] 回合回报非有限值 %r，本回合跳过元学习更新与基线刷新",
                episode_reward,
            )
        if reward is not None and self._last_reward is not None and self._total_updates > 0:
            delta = reward - self._last_reward
            self._update_bucket_reward(delta)

        # 2. ε-greedy 选择 λ 桶（探索：随机；利用：最高回报估计）
        if np.random.rand() < self.epsilon:
            idx = int(np.random.randint(0, self.n_buckets))
        else:
            idx = int(np.argmax(self._bucket_rewards))
        # 裁剪浮点边界（linspace 可能产生 0.15000000000000002 类误差）
        self._current_lambda = float(
            np.clip(self.lambda_candidates[idx], self.lambda_min, self.lambda_max)
        )
        self._bucket_counts[idx] += 1

        # 3. 记录历史
        self._total_updates += 1
        self._history.append({
            'episode': self._total_updates,
            'lambda': self._current_lambda,
            'bucket_index': idx,
            'bucket_reward_estimate': float(self._bucket_rewards[idx]),
            # 记净化后的值：NaN 会被 json.dumps 写成非标准 JSON 的 `NaN` 字面量，
            # Dashboard 侧 JSON.parse 直接抛错（历史记录是要导出的）。
            'episode_reward': reward,
        })

        # 4. 更新上一回合回报基线
        if reward is not None:
            self._last_reward = reward

        return self._current_lambda

    # ----------------------------------------------------------------------
    # 元学习内部更新
    # ----------------------------------------------------------------------

    def _update_bucket_reward(self, delta: float) -> None:
        """
        指数加权更新上一轮选中桶的回报估计（元学习核心）

        若上一轮没有选桶（首次调用），跳过。
        """
        if not self._history:
            return
        last_record = self._history[-1]
        idx = last_record.get('bucket_index')
        if idx is None:
            return
        idx = int(idx)
        # 指数加权：R_new = (1-α)*R_old + α*Δreward
        old = float(self._bucket_rewards[idx])
        self._bucket_rewards[idx] = (1.0 - self.reward_alpha) * old + self.reward_alpha * delta

    def select_lambda_by_metric(self, bridge_stats: Dict) -> float:
        """
        备选：基于链上指标的确定性子调度器（可解释性补充）

        当元学习样本不足时（前 few 个 episode），用比例式映射快速起步：
        λ 随综合指标（共识/合作/安全）单调上升，与 AdaptiveLambdaController 一致。
        """
        composite = self._composite_metric(bridge_stats)
        if not math.isfinite(composite):
            # 兜底：`np.clip` 不拦 NaN（只做 min/max 比较），NaN 会原样穿透成 λ。
            # 非有限综合值一律保持当前 λ，不输出 NaN。
            logger.warning(
                "[RLLambda] 综合指标非有限（%r），保持当前 λ=%r 不变",
                composite, self._current_lambda,
            )
            return self._current_lambda
        # 简单线性映射到 [lambda_min, lambda_max]
        t = np.clip(
            (composite - COMPOSITE_NORM_MIN) / COMPOSITE_NORM_SPAN, 0.0, 1.0
        )
        return float(self.lambda_min + t * (self.lambda_max - self.lambda_min))

    def _composite_metric(self, bridge_stats: Dict) -> float:
        """提取三大指标综合值（与 AdaptiveLambdaController 口径一致）

        F01 键契约修复（2026-11-05，补齐 2026-11-02 在 AdaptiveLambdaController
        上做过、此处漏掉的那一半）：``cw_pbft.get_consensus_stats()`` 只提供
        ``consensus_success_rate``，既没有 ``success_rate`` 也没有
        ``success_count``/``total_rounds``。旧实现读的全是不存在的键，于是
        `success_rate` 恒为默认 0.5 —— 实测「共识 0 成功 / 10 轮全失败」时
        本函数仍返回 0.5，与「没有数据」完全无法区分。合作率同理：旧实现读
        ``detector_stats``，而 ``bridge.get_stats()`` 从不产出该键（真实合作率
        由 ``on_episode_end`` 以顶层 ``cooperation_rate`` 注入），故也是恒 0.5。
        两个指标都钉死在 0.5 后，composite 与链上状态无关，λ 变成常数。
        """
        consensus_stats = bridge_stats.get('consensus_stats') or {}
        success_rate = None
        for key in ('consensus_success_rate', 'success_rate'):
            if key in consensus_stats:
                v = _finite_or_none(consensus_stats.get(key))
                if v is not None:
                    success_rate = _clamp_unit(v)
                    break
        if success_rate is None:
            sc = _finite_or_none(consensus_stats.get('success_count', 0))
            tc = _finite_or_none(consensus_stats.get('total_rounds', 0))
            if sc is not None and tc is not None and tc > 0:
                success_rate = _clamp_unit(sc / tc)
            else:
                success_rate = 0.5

        # 合作率：顶层 injection（权威，见 bc_integration.on_episode_end）
        # 优先，detector_stats 仅作兼容兜底
        coop_rate = None
        for key, table in (('cooperation_rate', bridge_stats),
                           ('cooperation_rate', bridge_stats.get('detector_stats') or {})):
            if table and key in table:
                v = _finite_or_none(table.get(key))
                if v is not None:
                    coop_rate = _clamp_unit(v)
                    break
        if coop_rate is None:
            coop_rate = 0.5

        sec_stats = bridge_stats.get('security_stats') or {}
        sec_pass = _finite_or_none(sec_stats.get('pass_count', 0))
        sec_fail = _finite_or_none(sec_stats.get('fail_count', 0))
        if sec_pass is not None and sec_fail is not None and (sec_pass + sec_fail) > 0:
            security_rate = _clamp_unit(sec_pass / (sec_pass + sec_fail))
        else:
            sp = _finite_or_none(bridge_stats.get('security_pass_count', 0))
            sf = _finite_or_none(bridge_stats.get('security_fail_count', 0))
            if sp is not None and sf is not None and (sp + sf) > 0:
                security_rate = _clamp_unit(sp / (sp + sf))
            else:
                security_rate = 0.5

        return float(
            COMPOSITE_W_CONSENSUS * success_rate
            + COMPOSITE_W_COOP * coop_rate
            + COMPOSITE_W_SECURITY * security_rate
        )

    # ----------------------------------------------------------------------
    # 兼容接口
    # ----------------------------------------------------------------------

    def get_adaptation_history(self) -> List[Dict]:
        """返回历史记录（与 AdaptiveLambdaController 兼容）"""
        return list(self._history)

    def get_stats(self) -> Dict:
        """返回统计信息（与 AdaptiveLambdaController 兼容）"""
        latest = self._history[-1] if self._history else {}
        return {
            'current_lambda': self._current_lambda,
            'lambda_base': self.lambda_base,
            'lambda_range': [self.lambda_min, self.lambda_max],
            'n_buckets': self.n_buckets,
            'epsilon': self.epsilon,
            'total_updates': self._total_updates,
            'bucket_rewards': [round(float(x), 4) for x in self._bucket_rewards],
            'bucket_counts': [int(x) for x in self._bucket_counts],
            'chosen_bucket_estimates': [round(float(x), 4) for x in self._bucket_rewards],
            'latest_record': latest,
            'controller_type': 'rl_lambda_meta_learning',
        }

    def reset(self) -> None:
        """重置元学习状态（新训练时调用）"""
        self._bucket_rewards = np.zeros(self.n_buckets)
        self._bucket_counts = np.zeros(self.n_buckets, dtype=int)
        self._current_lambda = self.lambda_base
        self._last_reward = None
        self._history.clear()
        self._total_updates = 0
        logger.info("[RLLambda] 元学习调度器已重置")

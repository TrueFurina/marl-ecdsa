"""
ConsensusRewardShaper 边界测试（RalphLoop 原子任务 E）
覆盖：shape_reward 各奖励分量、eta 缩放、边界输入、统计与重置
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from marl.integration.consensus_shaper import ConsensusRewardShaper

logging.basicConfig(level=logging.CRITICAL)


def _obs(n=3, n_lm=3):
    """构造 SimpleSpread 观测 [vel2, pos2, lm_rel(2*n_lm)]"""
    import numpy as np
    lm = np.random.rand(n, n_lm, 2) * 0.8 + 0.1
    rows = []
    for i in range(n):
        rows.append(np.array([0.1, 0.1, 0.5, 0.5] + lm[i].flatten().tolist()))
    return rows


class TestShapeRewardBasics:
    def test_shape_reward_returns_list(self):
        shaper = ConsensusRewardShaper(n_agents=3)
        obs = _obs(3)
        result = shaper.shape_reward(obs, obs, [0, 1, 2], ["a0", "a1", "a2"])
        assert isinstance(result, list)
        assert len(result) == 3

    def test_shape_reward_eta_scaling(self):
        """eta=0 → 塑形奖励全 0（边界：关闭塑形）"""
        shaper = ConsensusRewardShaper(n_agents=3, eta=0.0)
        obs = _obs(3)
        result = shaper.shape_reward(obs, obs, [0, 1, 2], ["a0", "a1", "a2"])
        assert all(abs(r) < 1e-9 for r in result)


class TestRewardComponents:
    def test_verification_bonus_applied(self):
        shaper = ConsensusRewardShaper(n_agents=3, verification_bonus=0.10, eta=1.0)
        obs = _obs(3)
        result = shaper.shape_reward(
            obs, obs, [0, 1, 2], ["a0", "a1", "a2"],
            verification_status=[True, True, True],
        )
        assert shaper._total_verification_bonus > 0

    def test_cooperation_bonus_from_status(self):
        shaper = ConsensusRewardShaper(n_agents=3, cooperation_bonus=0.08, eta=1.0)
        obs = _obs(3)
        result = shaper.shape_reward(
            obs, obs, [0, 1, 2], ["a0", "a1", "a2"],
            cooperation_status={"a0": True, "a1": False, "a2": True},
        )
        assert shaper._total_cooperation_bonus > 0

    def test_consensus_weight_bonus_high_weight_positive(self):
        """高于平均权重 → 正奖励"""
        shaper = ConsensusRewardShaper(n_agents=3, consensus_weight_scale=0.05, eta=1.0)
        obs = _obs(3)
        result = shaper.shape_reward(
            obs, obs, [0, 1, 2], ["a0", "a1", "a2"],
            consensus_weights={"a0": 0.6, "a1": 0.2, "a2": 0.2},
        )
        assert result[0] > 0  # a0 权重 0.6 > 1/3 平均

    def test_consensus_weight_bonus_high_beats_low(self):
        """相对断言（避免 potential-based 分量干扰绝对正负）：高权重塑造奖励 > 低权重"""
        shaper = ConsensusRewardShaper(n_agents=3, consensus_weight_scale=1.0, eta=1.0)
        obs = _obs(3)
        result = shaper.shape_reward(
            obs, obs, [0, 1, 2], ["a0", "a1", "a2"],
            consensus_weights={"a0": 0.6, "a1": 0.2, "a2": 0.2},
        )
        # a0 权重 0.6 高于 a1/a2 的 0.2 → a0 塑造奖励相对更高
        assert result[0] > result[1]
        assert result[0] > result[2]


class TestEdgeCases:
    def test_empty_verification_status(self):
        """verification_status 为空列表不崩溃"""
        shaper = ConsensusRewardShaper(n_agents=3)
        obs = _obs(3)
        result = shaper.shape_reward(
            obs, obs, [0, 1, 2], ["a0", "a1", "a2"],
            verification_status=[],
        )
        assert len(result) == 3

    def test_contribution_scores_none(self):
        """contribution_scores=None 不崩溃（内部有默认值）"""
        shaper = ConsensusRewardShaper(n_agents=3)
        obs = _obs(3)
        result = shaper.shape_reward(
            obs, obs, [0, 1, 2], ["a0", "a1", "a2"],
            contribution_scores=None,
        )
        assert len(result) == 3


class TestStatsAndReset:
    def test_get_stats(self):
        shaper = ConsensusRewardShaper(n_agents=3)
        obs = _obs(3)
        shaper.shape_reward(obs, obs, [0, 1, 2], ["a0", "a1", "a2"])
        stats = shaper.get_stats()
        assert isinstance(stats, dict)
        assert stats.get("step_count", 0) >= 1

    def test_reset(self):
        """reset 契约：重置势能历史（统计计数为累计设计，不重置）"""
        shaper = ConsensusRewardShaper(n_agents=3)
        obs = _obs(3)
        shaper.shape_reward(obs, obs, [0, 1, 2], ["a0", "a1", "a2"])
        assert shaper._prev_potentials != [0.0] * 3  # 势能已更新
        shaper.reset()
        assert shaper._prev_potentials == [0.0] * 3  # reset 后势能归零

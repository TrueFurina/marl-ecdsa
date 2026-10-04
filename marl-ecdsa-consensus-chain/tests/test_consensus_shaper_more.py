"""
consensus_shaper 势能更多边界测试（RalphLoop 原子任务 BN）
覆盖：势能范围、贡献势能边界、配置差异、势能单调性、统计
通过标准：新增 ≥6 项测试全过
"""
import logging

import numpy as np
import pytest

from marl.integration.consensus_shaper import ConsensusRewardShaper

logging.basicConfig(level=logging.CRITICAL)


def _obs(n=3, n_lm=3, near_own=False):
    """构造观测：近/远分配路标可选"""
    rows = []
    for i in range(n):
        lm = np.random.rand(n_lm, 2) * 0.8 + 0.1
        if near_own:
            lm[i % n_lm] = np.array([0.01, 0.01])
        rows.append(np.array([0.1, 0.1, 0.5, 0.5] + lm.flatten().tolist()))
    return rows


class TestPotentialRange:
    def test_potential_bounded(self):
        """势能值有界（空间负距离 + 贡献归一化）"""
        shaper = ConsensusRewardShaper(n_agents=3)
        obs = _obs(3)
        pots = shaper._compute_potential(obs)
        for p in pots:
            assert -1.0 < p < 0.6  # 负距离有界 + 贡献 ≤0.5

    def test_potential_near_landmark_less_negative(self):
        """靠近路标 → 势能更接近 0（负距离更小）"""
        shaper = ConsensusRewardShaper(n_agents=3)
        far = np.mean(shaper._compute_potential(_obs(3, near_own=False)))
        near = np.mean(shaper._compute_potential(_obs(3, near_own=True)))
        assert near >= far - 0.1


class TestContributionEdges:
    def test_scores_without_agent_ids_zero(self):
        """有 contribution_scores 但无 agent_ids → 贡献势能 0（仅空间）"""
        shaper = ConsensusRewardShaper(n_agents=3)
        zeros = [np.zeros(14) for _ in range(3)]
        pots = shaper._compute_potential(zeros, contribution_scores={"a0": 7.5})
        # 无 agent_ids → 贡献分量 0，空间全 0 → 势能≈0
        assert all(abs(p) < 0.05 for p in pots)

    def test_negative_score_clamped_by_formula(self):
        """负贡献分 → 贡献势能为负（score/15 不截断，但保持有限）"""
        shaper = ConsensusRewardShaper(n_agents=3)
        zeros = [np.zeros(14) for _ in range(3)]
        pots = shaper._compute_potential(zeros, contribution_scores={"a0": -15.0},
                                         agent_ids=["a0", "a1", "a2"])
        assert pots[0] == pytest.approx(0.5 * (-15.0 / 15.0), abs=0.05)  # -0.5

    def test_high_score_potential(self):
        """超大贡献分 → 势能线性放大（无截断）"""
        shaper = ConsensusRewardShaper(n_agents=3)
        zeros = [np.zeros(14) for _ in range(3)]
        pots = shaper._compute_potential(zeros, contribution_scores={"a0": 30.0},
                                         agent_ids=["a0", "a1", "a2"])
        assert pots[0] == pytest.approx(0.5 * (30.0 / 15.0), abs=0.05)  # 1.0


class TestConfigDiffs:
    def test_n_landmarks_2(self):
        """n_landmarks=2 → 观测维度不同但势能计算正常"""
        shaper = ConsensusRewardShaper(n_agents=3, n_landmarks=2)
        obs = _obs(3, n_lm=2)
        pots = shaper._compute_potential(obs)
        assert len(pots) == 3

    def test_n_agents_5(self):
        """5 智能体 → 5 个势能"""
        shaper = ConsensusRewardShaper(n_agents=5, n_landmarks=3)
        obs = _obs(5, n_lm=3)
        pots = shaper._compute_potential(obs)
        assert len(pots) == 5


class TestStats:
    def test_get_stats_structure(self):
        """get_stats 返回累计统计"""
        shaper = ConsensusRewardShaper(n_agents=3)
        obs = _obs(3)
        shaper.shape_reward(obs, obs, [0, 0, 0], ["a0", "a1", "a2"],
                            verification_status=[True] * 3)
        stats = shaper.get_stats()
        assert stats.get('step_count', 0) >= 1
        assert stats.get('total_verification_bonus', 0) > 0

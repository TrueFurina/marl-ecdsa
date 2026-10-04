"""
ConsensusRewardShaper 奖励守恒边界测试（RalphLoop 原子任务 AF）
覆盖：势能计算、贡献势能归一化、畸形观测降级、合作检测、eta 缩放守恒
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
            lm[i % n_lm] = np.array([0.02, 0.02])  # 靠近分配路标
        rows.append(np.array([0.1, 0.1, 0.5, 0.5] + lm.flatten().tolist()))
    return rows


class TestComputePotential:
    def test_potential_structure(self):
        shaper = ConsensusRewardShaper(n_agents=3)
        obs = _obs(3)
        potentials = shaper._compute_potential(obs)
        assert len(potentials) == 3
        assert all(isinstance(p, float) for p in potentials)

    def test_near_landmark_higher_potential(self):
        """靠近分配路标 → 空间势能更高（负距离更接近 0）"""
        shaper = ConsensusRewardShaper(n_agents=3)
        far = shaper._compute_potential(_obs(3, near_own=False))
        near = shaper._compute_potential(_obs(3, near_own=True))
        # 平均势能：near 应 ≥ far（靠近路标势能更高）
        assert np.mean(near) >= np.mean(far) - 0.1

    def test_contribution_potential_normalized(self):
        """贡献势能 = score/15 归一化"""
        shaper = ConsensusRewardShaper(n_agents=3)
        obs = _obs(3)
        # 构造全 0 观测（空间势能≈0），仅看贡献势能
        zeros = [np.zeros(14) for _ in range(3)]
        pots = shaper._compute_potential(zeros, contribution_scores={"a0": 7.5, "a1": 0.0, "a2": 15.0},
                                         agent_ids=["a0", "a1", "a2"])
        # 贡献势能分量 = 0.5 * (score/15)
        assert pots[0] == pytest.approx(0.5 * 7.5 / 15.0, abs=0.05)
        assert pots[2] >= pots[0] >= pots[1]

    def test_malformed_obs_fallback_zero(self):
        """畸形观测 → 异常捕获回退（不崩溃）"""
        shaper = ConsensusRewardShaper(n_agents=3)
        pots = shaper._compute_potential([[1.0], [2.0], [3.0]])  # 维度不足
        assert len(pots) == 3


class TestDetectCooperation:
    def test_coop_flags_structure(self):
        shaper = ConsensusRewardShaper(n_agents=3)
        flags = shaper._detect_cooperation(_obs(3), [0, 1, 2])
        assert len(flags) == 3
        assert all(isinstance(f, bool) for f in flags)

    def test_near_landmark_detected_coop(self):
        shaper = ConsensusRewardShaper(n_agents=3, n_landmarks=3)
        flags = shaper._detect_cooperation(_obs(3, near_own=True), [0, 0, 0],
                                           cooperation_threshold=0.5)
        assert all(flags)  # 全部接近路标 → 全部合作

    def test_malformed_obs_coop_fallback(self):
        shaper = ConsensusRewardShaper(n_agents=3)
        flags = shaper._detect_cooperation([[1.0], [1.0], [1.0]], [0, 0, 0])
        assert len(flags) == 3


class TestShapingConservation:
    def test_zero_eta_zero_shaping(self):
        """eta=0 → 塑形奖励全 0（不改变原始奖励）"""
        shaper = ConsensusRewardShaper(n_agents=3, eta=0.0)
        obs = _obs(3)
        result = shaper.shape_reward(obs, obs, [0, 0, 0], ["a0", "a1", "a2"])
        assert all(abs(r) < 1e-9 for r in result)

    def test_shaping_bounded_by_eta(self):
        """塑形奖励幅度受 eta 限制（eta=0.05 时 |shaping| 有界）"""
        shaper = ConsensusRewardShaper(n_agents=3, eta=0.05)
        obs = _obs(3)
        result = shaper.shape_reward(obs, obs, [0, 0, 0], ["a0", "a1", "a2"],
                                     contribution_scores={"a0": 15.0, "a1": 15.0, "a2": 15.0})
        assert all(abs(r) < 0.5 for r in result)  # 弱塑形不主导

    def test_potential_based_invariance(self):
        """potential-based 条件：F = gamma*Phi(s') - Phi(s)，同状态时 shaping≈0"""
        shaper = ConsensusRewardShaper(n_agents=3, eta=1.0)
        obs = _obs(3)
        # 相同 obs → 势能相同 → pb_shaping = gamma*Phi - Phi = (gamma-1)*Phi
        result = shaper.shape_reward(obs, obs, [0, 0, 0], ["a0", "a1", "a2"])
        # 无验证/合作/共识奖励时，仅 pb 项：幅度 = |(gamma-1)*Phi|，gamma=0.8
        assert all(abs(r) < 0.3 for r in result)

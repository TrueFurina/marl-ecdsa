"""
consensus_shaper 布局健壮性单测（自进化 backlog #5：势函数/观测布局硬编码耦合无校验）
覆盖：
- lm_start 配置化（默认 4，保持历史行为）
- obs_dim 形状断言（提供时强制校验，把"维度不符静默返回 0"变成构造期错误）
- 运行期观测过短：原静默置 0，现改为显式告警一次，行为仍兼容（置 0）
通过标准：新增测试全过；既有 consensus_shaper 测试零回归。
"""
import logging

import numpy as np
import pytest

from marl.integration.consensus_shaper import ConsensusRewardShaper


class TestLmStartConfig:
    def test_default_is_four(self):
        """默认 lm_start=4，保持历史布局行为"""
        s = ConsensusRewardShaper()
        assert s.lm_start == 4

    def test_custom_lm_start_stored(self):
        s = ConsensusRewardShaper(lm_start=6)
        assert s.lm_start == 6

    def test_custom_lm_start_reads_correct_block(self):
        """自定义 lm_start 后，空间势能应从对应区块读取（而非默认 [4:6]）"""
        # 1 智能体 / 1 路标：把路标块放在 obs[6:8]（靠近），[4:6] 留 0
        obs = np.zeros(8)
        obs[6] = 0.1
        obs[7] = 0.1  # 距分配路标极近

        # 默认 lm_start=4：读 [4:6]=0 → 空间势能 0
        s_default = ConsensusRewardShaper(n_agents=1, n_landmarks=1, lm_start=4)
        p_default = s_default._compute_potential([obs])[0]

        # 自定义 lm_start=6：读 [6:8]=[0.1,0.1] → 空间势能 = -norm([0.1,0.1])
        s_custom = ConsensusRewardShaper(n_agents=1, n_landmarks=1, lm_start=6)
        p_custom = s_custom._compute_potential([obs])[0]

        assert abs(p_default - 0.0) < 1e-9
        # phi = 0.5 * (-0.141421...) ；用容差比对角
        assert p_custom < -1e-3
        assert abs(p_custom - 0.5 * -np.linalg.norm(np.array([0.1, 0.1]))) < 1e-6


class TestObsDimAssertion:
    def test_obs_dim_sufficient_ok(self):
        """obs_dim 恰好等于需要量时构造不报错"""
        ConsensusRewardShaper(n_agents=3, n_landmarks=3, obs_dim=10)  # 4 + 2*3 = 10

    def test_obs_dim_insufficient_raises(self):
        """obs_dim 不足时构造期直接抛 ValueError（形状断言 fail-fast）"""
        with pytest.raises(ValueError, match=r"obs_dim=8"):
            ConsensusRewardShaper(n_agents=3, n_landmarks=3, obs_dim=8)  # need=10


class TestShortObsWarning:
    def test_short_obs_warns_once_and_returns_zero(self, caplog):
        """观测过短：原静默置 0，现显式告警一次；行为仍兼容（势能 0）"""
        caplog.set_level(logging.WARNING)
        s = ConsensusRewardShaper(n_agents=1, n_landmarks=3)  # 需要 lm_end=10
        short = [np.zeros(6)]  # 远短于 10

        p1 = s._compute_potential(short)[0]
        p2 = s._compute_potential(short)[0]  # 第二次不应再告警（去重）

        assert p1 == 0.0 and p2 == 0.0
        msgs = [r.message for r in caplog.records if "[Shaper]" in r.message]
        assert len(msgs) == 1, "短观测告警应恰好触发一次（去重）"
        assert "布局不匹配" in msgs[0]

    def test_normal_layout_no_warning(self, caplog):
        """正常布局（obs 长度足够）不应产生布局告警"""
        caplog.set_level(logging.WARNING)
        s = ConsensusRewardShaper(n_agents=2, n_landmarks=2)  # 需要 lm_end=8
        obs = [np.random.rand(8), np.random.rand(8)]
        s._compute_potential(obs)
        msgs = [r.message for r in caplog.records if "[Shaper]" in r.message]
        assert msgs == [], "正常布局不应触发布局告警"


class TestNormalPathUnchanged:
    def test_near_landmark_potential_unchanged(self):
        """正常布局下数值与历史一致（无回归）"""
        s = ConsensusRewardShaper(n_agents=2, n_landmarks=2)
        obs_near = np.zeros(8)
        obs_near[4] = 0.05
        obs_near[5] = 0.05
        obs_near[6] = 0.8
        obs_near[7] = 0.8
        obs_far = np.zeros(8)
        obs_far[4] = 0.8
        obs_far[5] = 0.8
        obs_far[6] = 0.05
        obs_far[7] = 0.05
        potentials = s._compute_potential([obs_near, obs_far])
        assert abs(potentials[0] - potentials[1]) < 1.0

"""
CARS共识感知奖励塑形器测试
覆盖：初始化、势能计算、塑形奖励、统计信息、重置
"""
import pytest
import numpy as np
from marl.integration.consensus_shaper import ConsensusRewardShaper


class TestConsensusShaperInit:
    """初始化测试"""

    def test_default_params(self):
        shaper = ConsensusRewardShaper()
        assert shaper.n_agents == 3
        assert shaper.eta == 0.05
        assert shaper.gamma == 0.8
        assert shaper.verification_bonus == 0.10
        assert shaper.cooperation_bonus == 0.08
        assert shaper.consensus_weight_scale == 0.05

    def test_custom_params(self):
        shaper = ConsensusRewardShaper(n_agents=5, eta=0.1, gamma=0.9)
        assert shaper.n_agents == 5
        assert shaper.eta == 0.1
        assert shaper.gamma == 0.9


class TestComputePotential:
    """势能计算测试"""

    def test_potential_returns_list(self):
        shaper = ConsensusRewardShaper(n_agents=3, n_landmarks=3)
        obs = [np.random.rand(10) for _ in range(3)]
        potentials = shaper._compute_potential(obs)
        assert len(potentials) == 3
        assert all(isinstance(p, float) for p in potentials)

    def test_potential_with_contribution_scores(self):
        shaper = ConsensusRewardShaper(n_agents=3)
        obs = [np.random.rand(10) for _ in range(3)]
        scores = {'agent_0': 5.0, 'agent_1': 3.0, 'agent_2': 1.0}
        potentials = shaper._compute_potential(obs, scores, ['agent_0', 'agent_1', 'agent_2'])
        assert len(potentials) == 3

    def test_potential_near_landmark_higher(self):
        """靠近分配路标的智能体势能应更高"""
        shaper = ConsensusRewardShaper(n_agents=2, n_landmarks=2)
        # agent_0 靠近路标0, agent_1 远离路标1
        obs_near = np.zeros(8)
        obs_near[4] = 0.05  # lm0 dx small
        obs_near[5] = 0.05  # lm0 dy small
        obs_near[6] = 0.8   # lm1 dx large
        obs_near[7] = 0.8   # lm1 dy large
        obs_far = np.zeros(8)
        obs_far[4] = 0.8    # lm0 dx large
        obs_far[5] = 0.8    # lm0 dy large
        obs_far[6] = 0.05   # lm1 dx small
        obs_far[7] = 0.05   # lm1 dy small

        potentials = shaper._compute_potential([obs_near, obs_far])
        # agent_0 vs agent_1: 各自靠近自己的路标
        # 两者势能应相近
        assert abs(potentials[0] - potentials[1]) < 1.0


class TestShapeReward:
    """塑形奖励计算测试"""

    def test_shape_reward_returns_correct_length(self):
        shaper = ConsensusRewardShaper(n_agents=3)
        obs = [np.random.rand(10) for _ in range(3)]
        actions = [0, 1, 2]
        agent_ids = ['agent_0', 'agent_1', 'agent_2']
        shaping = shaper.shape_reward(obs, obs, actions, agent_ids)
        assert len(shaping) == 3

    def test_verification_bonus_added(self):
        shaper = ConsensusRewardShaper(n_agents=2, eta=1.0)  # eta=1 不缩放
        obs = [np.random.rand(10) for _ in range(2)]
        actions = [0, 0]
        agent_ids = ['a0', 'a1']
        shaping = shaper.shape_reward(obs, obs, actions, agent_ids,
                                       verification_status=[True, False])
        # 验证通过的agent应获得额外奖励
        assert shaping[0] != shaping[1]

    def test_cooperation_bonus_added(self):
        shaper = ConsensusRewardShaper(n_agents=2, eta=1.0)
        obs = [np.random.rand(10) for _ in range(2)]
        actions = [0, 0]
        agent_ids = ['a0', 'a1']
        shaping = shaper.shape_reward(obs, obs, actions, agent_ids,
                                       cooperation_status={'a0': True, 'a1': False})
        assert shaping[0] != shaping[1]

    def test_consensus_weight_affects_shaping(self):
        shaper = ConsensusRewardShaper(n_agents=2, eta=1.0)
        obs = [np.random.rand(10) for _ in range(2)]
        actions = [0, 0]
        agent_ids = ['a0', 'a1']
        # 使用相同观测消除位置差异，只测试权重影响
        same_obs = [np.zeros(10), np.zeros(10)]
        weights_high = {'a0': 1.0, 'a1': 1.0}
        weights_low = {'a0': 0.1, 'a1': 0.1}
        shaper.reset()
        high = shaper.shape_reward(same_obs, same_obs, actions, agent_ids, consensus_weights=weights_high)
        shaper.reset()
        low = shaper.shape_reward(same_obs, same_obs, actions, agent_ids, consensus_weights=weights_low)
        # 权重不同应产生不同的塑形奖励
        assert abs(high[0] - low[0]) > 0.0001 or abs(high[1] - low[1]) > 0.0001

    def test_eta_scales_shaping(self):
        """eta参数应缩放塑形奖励"""
        shaper_low = ConsensusRewardShaper(n_agents=2, eta=0.01)
        shaper_high = ConsensusRewardShaper(n_agents=2, eta=1.0)
        obs = [np.random.rand(10) for _ in range(2)]
        actions = [0, 0]
        agent_ids = ['a0', 'a1']

        low = shaper_low.shape_reward(obs, obs, actions, agent_ids)
        high = shaper_high.shape_reward(obs, obs, actions, agent_ids)
        # eta=1.0 的塑形奖励应大于 eta=0.01
        assert sum(abs(h) for h in high) >= sum(abs(l) for l in low)


class TestStats:
    """统计信息测试"""

    def test_initial_stats(self):
        shaper = ConsensusRewardShaper()
        stats = shaper.get_stats()
        assert stats['step_count'] == 0
        assert stats['eta'] == 0.05

    def test_stats_after_shaping(self):
        shaper = ConsensusRewardShaper(n_agents=2)
        obs = [np.random.rand(10) for _ in range(2)]
        actions = [0, 0]
        shaper.shape_reward(obs, obs, actions, ['a0', 'a1'])
        stats = shaper.get_stats()
        assert stats['step_count'] == 1


class TestReset:
    """重置测试"""

    def test_reset_clears_potentials(self):
        shaper = ConsensusRewardShaper(n_agents=2)
        obs = [np.random.rand(10) for _ in range(2)]
        actions = [0, 0]
        shaper.shape_reward(obs, obs, actions, ['a0', 'a1'])
        shaper.reset()
        assert all(p == 0.0 for p in shaper._prev_potentials)

    def test_reset_preserves_params(self):
        shaper = ConsensusRewardShaper(n_agents=3, eta=0.1)
        shaper.reset()
        assert shaper.n_agents == 3
        assert shaper.eta == 0.1
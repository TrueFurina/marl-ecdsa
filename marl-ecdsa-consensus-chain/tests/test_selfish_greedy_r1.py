"""
贪心自私智能体边界测试（学长评价落第 2 项：理性自私策略化）
覆盖：greedy 模式动作选择 / random 模式回归 / 观测解析 / 防御回退
通过标准：新增 ≥6 项测试全过
"""
import logging

import numpy as np
import pytest

from marl.integration.selfish_agent import SelfishAgentWrapper

logging.basicConfig(level=logging.CRITICAL)


class MockBaseAgent:
    def get_action(self, obs, hidden_state=None):
        return 4, hidden_state


def _make_obs(lm_rel):
    """构造 SimpleSpread 布局观测：vel(2)+pos(2)+landmarks(2*n)+others(2*2)"""
    obs = [0.0, 0.0, 0.0, 0.0]
    for dx, dy in lm_rel:
        obs += [dx, dy]
    obs += [10.0, 10.0, -10.0, -10.0]  # 其他智能体（远）
    return np.array(obs, dtype=float)


class TestGreedyMode:
    def test_greedy_moves_toward_nearest(self):
        """最近路标在右侧 → 选右(4)"""
        w = SelfishAgentWrapper("a0", MockBaseAgent(), is_selfish=True,
                                betrayal_mode='greedy', n_landmarks=3)
        obs = _make_obs([(0.8, 0.0), (-0.9, 0.0), (0.0, 0.9)])
        a, _ = w.step(obs)
        assert a == 4

    def test_greedy_picks_nearest_of_three(self):
        """三个路标中选最近的（下方近 → 选下 2）"""
        w = SelfishAgentWrapper("a0", MockBaseAgent(), is_selfish=True,
                                betrayal_mode='greedy', n_landmarks=3)
        obs = _make_obs([(0.9, 0.9), (0.0, -0.3), (0.5, 0.5)])
        a, _ = w.step(obs)
        assert a == 2

    def test_greedy_always_betray(self):
        """greedy 每步都背叛（理性逐利）"""
        w = SelfishAgentWrapper("a0", MockBaseAgent(), is_selfish=True,
                                betrayal_mode='greedy', n_landmarks=3)
        obs = _make_obs([(0.1, 0.0), (0.9, 0.9), (-0.9, 0.9)])
        for _ in range(10):
            w.step(obs)
        assert w._betrayal_count == 10
        assert w.get_stats()['betrayal_rate'] == 1.0

    def test_greedy_ignores_base_agent(self):
        """greedy 不查询底层策略（mock 返回 4，路标在左 → 必为 3）"""
        w = SelfishAgentWrapper("a0", MockBaseAgent(), is_selfish=True,
                                betrayal_mode='greedy', n_landmarks=3)
        obs = _make_obs([(-0.7, 0.0), (0.9, 0.0), (0.0, -0.9)])
        a, _ = w.step(obs)
        assert a == 3

    def test_greedy_none_obs_fallback(self):
        """obs=None 防御回退：不崩溃，返回合法动作"""
        w = SelfishAgentWrapper("a0", MockBaseAgent(), is_selfish=True,
                                betrayal_mode='greedy', n_landmarks=3)
        a, _ = w.step(None)
        assert 0 <= a < 5

    def test_greedy_up_when_above(self):
        """最近路标在上方 → 选上(1)"""
        w = SelfishAgentWrapper("a0", MockBaseAgent(), is_selfish=True,
                                betrayal_mode='greedy', n_landmarks=2)
        obs = _make_obs([(0.0, 0.6), (-0.9, -0.9)])
        a, _ = w.step(obs)
        assert a == 1


class TestRandomModeRegression:
    def test_default_mode_is_random(self):
        """默认 random（旧行为可复现）"""
        w = SelfishAgentWrapper("a0", MockBaseAgent(), is_selfish=True)
        assert w.betrayal_mode == 'random'

    def test_honest_never_betray(self):
        """诚实模式永不背叛"""
        w = SelfishAgentWrapper("a0", MockBaseAgent(), is_selfish=False,
                                betrayal_mode='greedy')
        for _ in range(5):
            w.step(_make_obs([(0.1, 0.0), (0.9, 0.0), (0.0, 0.9)]))
        assert w._betrayal_count == 0

    def test_prob_zero_never_betray(self):
        """random 模式 prob=0 永不背叛"""
        w = SelfishAgentWrapper("a0", MockBaseAgent(), is_selfish=True,
                                betrayal_prob=0.0, betrayal_mode='random')
        for _ in range(20):
            w.step(_make_obs([(0.1, 0.0), (0.9, 0.0), (0.0, 0.9)]))
        assert w._betrayal_count == 0

    def test_reward_signal_split(self):
        """奖励信号分流：自私取局部、诚实取全局"""
        s = SelfishAgentWrapper("a0", MockBaseAgent(), is_selfish=True)
        h = SelfishAgentWrapper("a1", MockBaseAgent(), is_selfish=False)
        assert s.get_reward(-10.0, -1.0) == -1.0
        assert h.get_reward(-10.0, -1.0) == -10.0

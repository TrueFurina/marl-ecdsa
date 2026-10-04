"""
SimpleSpreadEnv 环境边界测试（RalphLoop 原子任务 P）
覆盖：维度、reset、step（None/越界动作）、done 条件、奖励结构
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from marl.envs.simple_spread import SimpleSpreadEnv

logging.basicConfig(level=logging.CRITICAL)


class TestDims:
    def test_obs_dim_formula(self):
        env = SimpleSpreadEnv(n_agents=3, n_landmarks=3)
        expected = 2 + 2 + 2 * 3 + 2 * (3 - 1)  # vel+pos+lm+other_agents
        assert env.obs_dim == expected == 14

    def test_state_dim_formula(self):
        env = SimpleSpreadEnv(n_agents=3, n_landmarks=3)
        assert env.state_dim == (2 + 2) * 3 + 2 * 3 == 18

    def test_n_actions(self):
        env = SimpleSpreadEnv()
        assert env.n_actions == 5  # 无操作/上下左右


class TestReset:
    def test_reset_returns_observations(self):
        env = SimpleSpreadEnv(n_agents=3, n_landmarks=3)
        obs = env.reset()
        assert len(obs) == 3
        assert len(obs[0]) == env.obs_dim == 14

    def test_reset_resets_step_count(self):
        env = SimpleSpreadEnv()
        for _ in range(5):
            env.step([0, 0, 0])
        env.reset()
        assert env._step_count == 0


class TestStep:
    def test_step_valid_actions(self):
        env = SimpleSpreadEnv(n_agents=3)
        env.reset()
        obs, grewards, lrewards, done, info = env.step([0, 1, 4])
        assert len(obs) == 3
        assert len(grewards) == 3
        assert len(lrewards) == 3
        assert isinstance(done, bool)
        assert 'coverage' in info

    def test_step_none_action_defaults_zero(self):
        """None 动作 → 默认为无操作(0)，不崩溃"""
        env = SimpleSpreadEnv(n_agents=3)
        env.reset()
        obs, _, _, done, _ = env.step([None, None, None])
        assert len(obs) == 3

    def test_step_out_of_range_action_modded(self):
        """越界动作 → 取模 n_actions，不崩溃"""
        env = SimpleSpreadEnv(n_agents=3)
        env.reset()
        obs, _, _, _, _ = env.step([99, -1, 7])
        assert len(obs) == 3

    def test_step_done_after_max_steps(self):
        env = SimpleSpreadEnv(n_agents=3, max_steps=3)
        env.reset()
        done = False
        for _ in range(3):
            _, _, _, done, _ = env.step([0, 0, 0])
        assert done is True  # 达到最大步数


class TestRewards:
    def test_rewards_are_floats(self):
        env = SimpleSpreadEnv(n_agents=3)
        env.reset()
        _, grewards, lrewards, _, _ = env.step([1, 1, 1])
        assert all(isinstance(r, float) for r in grewards)
        assert all(isinstance(r, float) for r in lrewards)

    def test_global_rewards_identical_across_agents(self):
        """全局奖励对所有智能体相同（覆盖奖励语义）"""
        env = SimpleSpreadEnv(n_agents=3)
        env.reset()
        _, grewards, _, _, _ = env.step([0, 0, 0])
        assert len(set(grewards)) == 1


class TestGetState:
    def test_get_state_dim(self):
        env = SimpleSpreadEnv(n_agents=3, n_landmarks=3)
        env.reset()
        state = env.get_state()
        assert len(state) == env.state_dim == 18

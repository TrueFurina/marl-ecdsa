"""MAPPO Critic 回归目标的形状不变量（2026-11-02）。

旧实现用 ``np.repeat(returns, n_agents)[:T]``：n_agents>1 时那是
``[r0,r0,r1,...]``，与逐时间步的 v_pred 错位，critic 学到的是错位的目标。
正确目标就是 ``returns`` 本身（每个时间步一个团队回报）。
"""
import numpy as np
import pytest

from marl.algorithms.mappo import _critic_targets


def test_critic_targets_are_per_timestep_returns():
    T, n_agents = 3, 2
    returns = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    targets = _critic_targets(returns, n_agents, T)
    assert np.array_equal(targets, returns), f"目标错位：{targets}"

    # 旧实现的结果在 n_agents>1 时必须与正确目标不同（证明这条回归真的在守）
    wrong = np.repeat(returns, n_agents)[:T]
    assert not np.array_equal(wrong, returns), "旧实现的错位结果不应等于正确目标"


def test_critic_targets_single_agent_matches_returns():
    returns = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    assert np.array_equal(_critic_targets(returns, 1, 3), returns)


def test_critic_targets_rejects_length_mismatch():
    with pytest.raises(ValueError):
        _critic_targets(np.array([1.0, 2.0]), n_agents=2, T=3)

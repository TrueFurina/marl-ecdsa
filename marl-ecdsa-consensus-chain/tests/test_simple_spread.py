"""
SimpleSpreadEnv 环境测试
覆盖：reset/step、观测维度、奖励计算、覆盖检测、边界处理
"""
import pytest
import numpy as np
import sys
sys.path.insert(0, '.')

from marl.envs.simple_spread import SimpleSpreadEnv


@pytest.fixture
def env():
    np.random.seed(42)
    return SimpleSpreadEnv(n_agents=3, n_landmarks=3, max_steps=25)


class TestInitialization:
    """环境初始化"""

    def test_default_params(self):
        env = SimpleSpreadEnv()
        assert env.n_agents == 3
        assert env.n_landmarks == 3
        assert env.max_steps == 25

    def test_obs_dim(self, env):
        # vel(2) + pos(2) + landmarks_rel(2*3) + other_agents_rel(2*2) = 14
        assert env.obs_dim == 14

    def test_state_dim(self, env):
        # (pos+vel)*3 + landmark_pos*3 = 12 + 6 = 18
        assert env.state_dim == 18

    def test_n_actions(self, env):
        assert env.n_actions == 5

    def test_action_forces(self, env):
        assert env._action_forces.shape == (5, 2)
        assert np.allclose(env._action_forces[0], [0, 0])  # no-op


class TestReset:
    """reset 方法"""

    def test_reset_returns_observations(self, env):
        obs = env.reset()
        assert len(obs) == 3
        for o in obs:
            assert o.shape == (env.obs_dim,)

    def test_reset_step_count_zero(self, env):
        env.reset()
        assert env._step_count == 0

    def test_reset_new_positions(self, env):
        obs1 = env.reset()
        pos1 = env._agent_pos.copy()
        obs2 = env.reset()
        # 随机初始化应产生不同位置（极大概率）
        assert not np.allclose(pos1, env._agent_pos)


class TestStep:
    """step 方法"""

    def test_step_returns_correct_types(self, env):
        env.reset()
        obs, global_r, local_r, done, info = env.step([0, 0, 0])
        assert len(obs) == 3
        assert len(global_r) == 3
        assert len(local_r) == 3
        assert isinstance(done, bool)
        assert isinstance(info, dict)

    def test_step_increments_count(self, env):
        env.reset()
        env.step([0, 0, 0])
        assert env._step_count == 1
        env.step([1, 2, 3])
        assert env._step_count == 2

    def test_done_after_max_steps(self, env):
        env.reset()
        for _ in range(25):
            _, _, _, done, _ = env.step([0, 0, 0])
        assert done is True

    def test_not_done_before_max_steps(self, env):
        env.reset()
        _, _, _, done, _ = env.step([0, 0, 0])
        assert done is False

    def test_noop_action_no_movement(self, env):
        env.reset()
        pos_before = env._agent_pos.copy()
        env.step([0, 0, 0])
        # no-op 应几乎不移动（阻尼衰减）
        assert np.allclose(pos_before, env._agent_pos, atol=0.01)

    def test_move_action_changes_position(self, env):
        env.reset()
        pos_before = env._agent_pos.copy()
        for _ in range(5):
            env.step([1, 1, 1])  # up
        assert not np.allclose(pos_before, env._agent_pos)

    def test_boundary_clipping(self, env):
        env.reset()
        for _ in range(50):
            env.step([4, 4, 4])  # right, would go beyond world_size
        for i in range(3):
            assert env._agent_pos[i][0] <= env.world_size + 0.01

    def test_info_contains_coverage(self, env):
        env.reset()
        _, _, _, _, info = env.step([0, 0, 0])
        assert "coverage" in info
        assert "step" in info
        assert "agent_positions" in info


class TestRewards:
    """奖励计算"""

    def test_global_reward_negative(self, env):
        """全局奖励（距离惩罚）应为负"""
        env.reset()
        _, global_r, _, _, _ = env.step([0, 0, 0])
        for r in global_r:
            assert r <= 0.0

    def test_local_reward_includes_distance(self, env):
        """局部奖励 = -dist + coverage_bonus"""
        env.reset()
        _, _, local_r, _, _ = env.step([0, 0, 0])
        for r in local_r:
            # 没覆盖时纯距离惩罚，覆盖时加 bonus
            assert isinstance(r, float)

    def test_coverage_bonus_positive(self, env):
        """覆盖目标点时获得正向bonus"""
        env.reset()
        # 强行将agent放到landmark上
        env._agent_pos = env._landmark_pos.copy()
        _, _, local_r, _, _ = env.step([0, 0, 0])
        for r in local_r:
            assert r > 0  # coverage_bonus(2.0) - dist(~0) > 0


class TestCoverage:
    """覆盖检测"""

    def test_check_coverage_false_initially(self, env):
        env.reset()
        # 随机位置几乎不可能覆盖
        assert env._check_coverage() is False

    def test_check_coverage_true_when_covered(self, env):
        env.reset()
        env._agent_pos = env._landmark_pos.copy()
        assert env._check_coverage() is True

    def test_coverage_ends_episode(self, env):
        env.reset()
        env._agent_pos = env._landmark_pos.copy()
        _, _, _, done, info = env.step([0, 0, 0])
        assert done is True
        assert info["coverage"] is True


class TestGetState:
    """全局状态"""

    def test_state_dim_correct(self, env):
        env.reset()
        state = env.get_state()
        assert state.shape == (env.state_dim,)

    def test_state_contains_positions(self, env):
        env.reset()
        state = env.get_state()
        # 前6个 = agent_pos flatten (3*2)
        assert np.allclose(state[:6], env._agent_pos.flatten())


class TestRenderText:
    """文本渲染"""

    def test_render_returns_string(self, env):
        env.reset()
        text = env.render_text()
        assert isinstance(text, str)
        assert "agent_0" in text
        assert "landmark_0" in text

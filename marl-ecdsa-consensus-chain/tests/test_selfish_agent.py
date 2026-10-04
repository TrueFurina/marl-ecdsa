"""
自私智能体封装测试
覆盖：诚实/自私模式、背叛概率、奖励选择、统计接口
"""
import pytest
import random
import sys
sys.path.insert(0, '.')

from marl.integration.selfish_agent import SelfishAgentWrapper, create_agents


class MockBaseAgent:
    """模拟底层MARL智能体"""
    def __init__(self, agent_id=None, **kwargs):
        self.agent_id = agent_id

    def get_action(self, obs, hidden_state=None):
        return 1, hidden_state  # 始终返回动作1


class TestHonestMode:
    """诚实模式"""

    def test_honest_uses_global_reward(self):
        wrapper = SelfishAgentWrapper("a0", MockBaseAgent(), is_selfish=False)
        assert wrapper.get_reward(global_reward=10.0, local_reward=5.0) == 10.0

    def test_honest_never_betrays(self):
        wrapper = SelfishAgentWrapper("a0", MockBaseAgent(), is_selfish=False)
        for _ in range(100):
            assert wrapper.should_betray() is False

    def test_honest_step_returns_base_action(self):
        wrapper = SelfishAgentWrapper("a0", MockBaseAgent(), is_selfish=False)
        action, _ = wrapper.step(obs=None)
        assert action == 1  # MockBaseAgent 返回1


class TestSelfishMode:
    """自私模式"""

    def test_selfish_uses_local_reward(self):
        wrapper = SelfishAgentWrapper("a0", MockBaseAgent(), is_selfish=True)
        assert wrapper.get_reward(global_reward=10.0, local_reward=5.0) == 5.0

    def test_selfish_can_betray(self):
        random.seed(42)
        wrapper = SelfishAgentWrapper("a0", MockBaseAgent(), is_selfish=True, betrayal_prob=1.0)
        # betrayal_prob=1.0 → 总是背叛
        assert wrapper.should_betray() is True

    def test_selfish_never_betray_prob_zero(self):
        wrapper = SelfishAgentWrapper("a0", MockBaseAgent(), is_selfish=True, betrayal_prob=0.0)
        for _ in range(100):
            assert wrapper.should_betray() is False

    def test_betray_replaces_action(self):
        random.seed(42)
        wrapper = SelfishAgentWrapper("a0", MockBaseAgent(), is_selfish=True, betrayal_prob=1.0, n_actions=5)
        action, _ = wrapper.step(obs=None)
        # 背叛时随机选择动作（0-4），不再是基础agent的1
        assert isinstance(action, int)
        assert 0 <= action <= 4

    def test_betrayal_count_incremented(self):
        random.seed(42)
        wrapper = SelfishAgentWrapper("a0", MockBaseAgent(), is_selfish=True, betrayal_prob=1.0)
        wrapper.step(obs=None)
        wrapper.step(obs=None)
        assert wrapper._betrayal_count == 2


class TestStats:
    """统计接口"""

    def test_initial_stats(self):
        wrapper = SelfishAgentWrapper("a0", MockBaseAgent(), is_selfish=False)
        stats = wrapper.get_stats()
        assert stats["agent_id"] == "a0"
        assert stats["is_selfish"] is False
        assert stats["betrayal_count"] == 0
        assert stats["total_steps"] == 0
        assert stats["betrayal_rate"] == 0.0

    def test_stats_after_steps(self):
        random.seed(42)
        wrapper = SelfishAgentWrapper("a0", MockBaseAgent(), is_selfish=True, betrayal_prob=1.0)
        for _ in range(10):
            wrapper.step(obs=None)
        stats = wrapper.get_stats()
        assert stats["total_steps"] == 10
        assert stats["betrayal_count"] == 10
        assert stats["betrayal_rate"] == 1.0

    def test_betrayal_rate_partial(self):
        random.seed(42)
        wrapper = SelfishAgentWrapper("a0", MockBaseAgent(), is_selfish=False)
        for _ in range(10):
            wrapper.step(obs=None)
        stats = wrapper.get_stats()
        assert stats["betrayal_rate"] == 0.0  # 诚实模式不背叛


class TestCreateAgents:
    """批量创建智能体"""

    def test_create_all_honest(self):
        agents = create_agents(n_agents=3, selfish_ratio=0.0, base_agent_class=MockBaseAgent)
        assert len(agents) == 3
        assert all(not a.is_selfish for a in agents)

    def test_create_with_selfish_ratio(self):
        agents = create_agents(n_agents=3, selfish_ratio=0.3, base_agent_class=MockBaseAgent)
        assert len(agents) == 3
        # n_selfish = max(1, round(3*0.3)) = max(1, 1) = 1
        assert sum(1 for a in agents if a.is_selfish) == 1

    def test_create_half_selfish(self):
        agents = create_agents(n_agents=4, selfish_ratio=0.5, base_agent_class=MockBaseAgent)
        assert len(agents) == 4
        assert sum(1 for a in agents if a.is_selfish) == 2

    def test_create_no_base_agent(self):
        """base_agent_class=None 时仍可创建"""
        agents = create_agents(n_agents=2, selfish_ratio=0.0, base_agent_class=None)
        assert len(agents) == 2
        assert all(a.base_agent is None for a in agents)

    def test_selfish_gets_betrayal_prob(self):
        agents = create_agents(n_agents=3, selfish_ratio=0.3, base_agent_class=MockBaseAgent)
        selfish_agents = [a for a in agents if a.is_selfish]
        honest_agents = [a for a in agents if not a.is_selfish]
        assert all(a.betrayal_prob == 0.3 for a in selfish_agents)
        assert all(a.betrayal_prob == 0.0 for a in honest_agents)

    def test_agent_ids_assigned(self):
        agents = create_agents(n_agents=3, selfish_ratio=0.0, base_agent_class=MockBaseAgent)
        for i, a in enumerate(agents):
            assert a.agent_id == f"agent_{i}"

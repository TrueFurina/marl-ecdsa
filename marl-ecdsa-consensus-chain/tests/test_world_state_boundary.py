"""
WorldState 边界测试（RalphLoop 原子任务 J）
覆盖：注册去重、查询缺失、积分边界（KeyError/未注册）、惩罚分级、状态
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from blockchain.ledger.world_state import WorldState, AgentStatus

logging.basicConfig(level=logging.CRITICAL)


@pytest.fixture
def ws():
    state = WorldState()
    state.register_agent("agent_0", "0x" + "ab" * 32)
    state.register_agent("agent_1", "0x" + "cd" * 32)
    return state


class TestRegister:
    def test_register_new_agent(self):
        ws = WorldState()
        assert ws.register_agent("agent_0", "pk_hex") is True
        assert ws.is_registered("agent_0") is True

    def test_duplicate_register_rejected(self, ws):
        assert ws.register_agent("agent_0", "another_pk") is False  # 重复注册拒绝

    def test_register_initializes_score_and_behavior(self, ws):
        assert ws.get_score("agent_0") == 0.0
        assert ws.get_contribution("agent_0") == 0.0


class TestQueries:
    def test_get_public_key_missing_returns_none(self, ws):
        assert ws.get_public_key("ghost") is None

    def test_get_agent_status_missing_returns_none(self, ws):
        assert ws.get_agent_status("ghost") is None

    def test_is_active_registered(self, ws):
        assert ws.is_active("agent_0") is True

    def test_is_active_banned(self, ws):
        ws._identities["agent_1"].status = AgentStatus.BANNED
        assert ws.is_active("agent_1") is False


class TestScores:
    def test_add_score_and_get(self, ws):
        ws.add_score("agent_0", 5.0)
        assert ws.get_score("agent_0") == 5.0

    def test_add_score_unregistered_noop(self, ws):
        ws.add_score("ghost", 5.0)  # 未注册不崩溃，无效果
        assert "ghost" not in ws.get_all_scores()

    def test_get_score_unregistered_raises_keyerror(self, ws):
        """P2-13：未注册 agent 获取积分抛 KeyError（防注册遗漏被掩盖）"""
        with pytest.raises(KeyError):
            ws.get_score("ghost")

    def test_get_contribution_unregistered_returns_zero(self, ws):
        assert ws.get_contribution("ghost") == 0.0

    def test_positive_score_adds_contribution(self, ws):
        ws.add_score("agent_0", 3.0)
        assert ws.get_contribution("agent_0") == 3.0
        ws.add_score("agent_0", -1.0)  # 负值不计入累计贡献
        assert ws.get_contribution("agent_0") == 3.0


class TestPenalty:
    def test_betrayal_increments_count(self, ws):
        ws.record_betrayal("agent_0", 1)
        assert ws._scores["agent_0"].betrayal_count == 1

    def test_betrayal_unregistered_noop(self, ws):
        ws.record_betrayal("ghost", 1)  # 未注册不崩溃
        assert "ghost" not in ws.get_all_scores()

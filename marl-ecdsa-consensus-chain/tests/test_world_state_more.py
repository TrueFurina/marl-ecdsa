"""
WorldState 更多边界测试（RalphLoop 原子任务 BJ）
覆盖：状态枚举流转、积分边界、系统状态累计、活跃性多状态
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


class TestStatusTransitions:
    def test_initial_status_active(self, ws):
        assert ws.get_agent_status("agent_0") == AgentStatus.ACTIVE

    def test_set_all_statuses(self, ws):
        """枚举各状态均可设置"""
        for status in [AgentStatus.ACTIVE, AgentStatus.WARNING,
                       AgentStatus.DEMOTED, AgentStatus.BANNED]:
            ws.set_agent_status("agent_0", status)
            assert ws.get_agent_status("agent_0") == status

    def test_is_active_multi_status(self, ws):
        """is_active：仅 BANNED 为 False，其余为 True"""
        for status in [AgentStatus.ACTIVE, AgentStatus.WARNING, AgentStatus.DEMOTED]:
            ws.set_agent_status("agent_0", status)
            assert ws.is_active("agent_0") is True
        ws.set_agent_status("agent_0", AgentStatus.BANNED)
        assert ws.is_active("agent_0") is False


class TestScoreEdges:
    def test_negative_score_allowed(self, ws):
        """积分为负（惩罚场景）"""
        ws.add_score("agent_0", -50.0)
        assert ws.get_score("agent_0") == -50.0

    def test_large_score(self, ws):
        ws.add_score("agent_0", 1e9)
        assert ws.get_score("agent_0") == 1e9

    def test_contribution_only_positive(self, ws):
        """累计贡献仅记录正增量（负增量不计入）"""
        ws.add_score("agent_0", 10.0)
        ws.add_score("agent_0", -5.0)
        assert ws.get_contribution("agent_0") == 10.0  # -5 未计入

    def test_all_scores_snapshot(self, ws):
        """get_all_scores 返回快照（修改副本不影响内部）"""
        ws.add_score("agent_0", 5.0)
        snapshot = ws.get_all_scores()
        snapshot["agent_0"] = 999.0
        assert ws.get_score("agent_0") == 5.0  # 内部未变


class TestSystemState:
    def test_system_state_accumulates(self, ws):
        """多次 update_system_state → total_transactions 累计"""
        ws.update_system_state(height=1, tx_count=10, online_count=2)
        ws.update_system_state(height=2, tx_count=5, online_count=3)
        state = ws.get_system_state()
        assert state["total_transactions"] == 15  # 10+5 累计
        assert state["block_height"] == 2  # 最新高度
        assert state["online_agents"] == 3

    def test_system_state_initial(self, ws):
        state = ws.get_system_state()
        assert state["registered_agents"] == 2
        assert state["total_transactions"] == 0


class TestIdentityEdges:
    def test_pubkey_roundtrip(self, ws):
        """注册公钥可查询往返"""
        assert ws.get_public_key("agent_0") == "0x" + "ab" * 32

    def test_get_all_agent_ids(self, ws):
        ids = ws.get_all_agent_ids()
        assert set(ids) == {"agent_0", "agent_1"}

    def test_unregistered_pubkey_none(self, ws):
        assert ws.get_public_key("ghost") is None

    def test_consensus_weight_default(self, ws):
        """注册后默认共识权重"""
        assert ws.get_consensus_weight("agent_0") > 0

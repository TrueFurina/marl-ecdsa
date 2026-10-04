"""
WorldState summary 边界测试（RalphLoop 原子任务 V）
覆盖：get_agent_summary、get_all_agents_summary、系统状态、权重/状态更新
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


class TestAgentSummary:
    def test_summary_structure(self, ws):
        summary = ws.get_agent_summary("agent_0")
        for key in ['agent_id', 'status', 'consensus_weight', 'score',
                    'cumulative_contribution', 'betrayal_count',
                    'cooperation_rounds', 'last_active_block']:
            assert key in summary

    def test_summary_unregistered_returns_empty(self, ws):
        assert ws.get_agent_summary("ghost") == {}

    def test_summary_reflects_state(self, ws):
        ws.add_score("agent_0", 10.0)
        ws.record_cooperation("agent_0")
        ws.update_consensus_weight("agent_0", 0.8)
        summary = ws.get_agent_summary("agent_0")
        assert summary["score"] == 10.0
        assert summary["consensus_weight"] == 0.8
        assert summary["cooperation_rounds"] == 1

    def test_summary_all_agents(self, ws):
        summaries = ws.get_all_agents_summary()
        assert len(summaries) == 2
        ids = {s["agent_id"] for s in summaries}
        assert ids == {"agent_0", "agent_1"}


class TestSystemState:
    def test_system_state_initial(self, ws):
        state = ws.get_system_state()
        assert state["registered_agents"] == 2
        assert state["total_transactions"] == 0

    def test_system_state_updated(self, ws):
        ws.update_system_state(height=5, tx_count=10, online_count=2)
        state = ws.get_system_state()
        assert state["block_height"] == 5
        assert state["total_transactions"] == 10
        assert state["online_agents"] == 2


class TestWeightAndStatus:
    def test_update_consensus_weight(self, ws):
        ws.update_consensus_weight("agent_0", 0.6)
        assert ws.get_consensus_weight("agent_0") == 0.6

    def test_update_weight_unregistered_noop(self, ws):
        ws.update_consensus_weight("ghost", 0.5)  # 不崩溃
        assert ws.get_consensus_weight("ghost") == 0.0

    def test_set_agent_status(self, ws):
        ws.set_agent_status("agent_0", AgentStatus.BANNED)
        assert ws.get_agent_status("agent_0") == AgentStatus.BANNED

    def test_set_status_unregistered_noop(self, ws):
        ws.set_agent_status("ghost", AgentStatus.BANNED)  # 不崩溃
        assert ws.get_agent_status("ghost") is None


class TestBetrayal:
    def test_get_betrayal_count(self, ws):
        ws.record_betrayal("agent_0", 1)
        ws.record_betrayal("agent_0", 2)
        assert ws.get_betrayal_count("agent_0") == 2

    def test_get_betrayal_count_unregistered_zero(self, ws):
        assert ws.get_betrayal_count("ghost") == 0

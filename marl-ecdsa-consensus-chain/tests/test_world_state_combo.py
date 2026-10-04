"""
WorldState 剩余边界测试（RalphLoop 原子任务 CB）
覆盖：积分+行为+摘要联动、多智能体独立、背叛惩罚链、系统状态联动
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
    return ws_fixture_dynamic(state)


def ws_fixture_dynamic(state):
    return state


class TestIntegratedFlow:
    def test_score_behavior_summary_flow(self, ws):
        """积分+行为+摘要联动：完整训练周期后的状态一致"""
        ws.add_score("agent_0", 15.0)
        ws.record_cooperation("agent_0")
        ws.record_action("agent_0", "hash_abc", 3)
        summary = ws.get_agent_summary("agent_0")
        assert summary["score"] == 15.0
        assert summary["cooperation_rounds"] == 1
        assert summary["last_active_block"] == 3

    def test_betrayal_chain(self, ws):
        """背叛惩罚链：record_betrayal → 计数 → 摘要"""
        ws.record_betrayal("agent_0", 5)
        ws.record_betrayal("agent_0", 6)
        assert ws.get_betrayal_count("agent_0") == 2
        summary = ws.get_agent_summary("agent_0")
        assert summary["betrayal_count"] == 2

    def test_register_system_summary_flow(self, ws):
        """注册+系统状态+摘要联动"""
        ws.update_system_state(height=10, tx_count=50, online_count=2)
        state = ws.get_system_state()
        assert state["block_height"] == 10
        assert state["registered_agents"] == 2
        summaries = ws.get_all_agents_summary()
        assert len(summaries) == 2


class TestMultiAgentIndependence:
    def test_agents_isolated_scores(self, ws):
        """多智能体积分互相独立"""
        ws.add_score("agent_0", 10.0)
        ws.add_score("agent_1", -5.0)
        assert ws.get_score("agent_0") == 10.0
        assert ws.get_score("agent_1") == -5.0

    def test_agents_isolated_status(self, ws):
        """多智能体状态互相独立"""
        ws.set_agent_status("agent_0", AgentStatus.BANNED)
        assert ws.is_active("agent_0") is False
        assert ws.is_active("agent_1") is True  # 未受影响

    def test_agents_isolated_behavior(self, ws):
        """多智能体行为记录独立"""
        ws.record_action("agent_0", "h1", 1)
        ws.record_betrayal("agent_1", 2)
        assert ws._behaviors["agent_0"].action_hashes == ["h1"]
        assert ws._behaviors["agent_1"].betrayal_rounds == [2]


class TestScoreContributions:
    def test_mixed_deltas_contribution(self, ws):
        """混合增量：仅正增量计入累计贡献"""
        ws.add_score("agent_0", 8.0)
        ws.add_score("agent_0", -3.0)
        ws.add_score("agent_0", 5.0)
        assert ws.get_contribution("agent_0") == 13.0  # 8+5，-3 不计

    def test_score_then_summary_consistency(self, ws):
        """积分与摘要一致"""
        ws.add_score("agent_0", 7.5)
        assert ws.get_score("agent_0") == 7.5
        assert ws.get_agent_summary("agent_0")["score"] == 7.5


class TestIdentityConsistency:
    def test_pubkey_consistent_across_queries(self, ws):
        """公钥查询一致性"""
        pk = ws.get_public_key("agent_0")
        assert pk == "0x" + "ab" * 32
        assert ws.get_agent_summary("agent_0")["agent_id"] == "agent_0"

    def test_all_agent_ids_order_stable(self, ws):
        """注册顺序稳定（get_all_agent_ids 保持插入序）"""
        ids = ws.get_all_agent_ids()
        assert ids == ["agent_0", "agent_1"]  # 注册顺序

"""
WorldState 剩余组合测试（RalphLoop 原子任务 CL）
覆盖：惩罚链+摘要联动、状态+积分+贡献联动、跨操作一致性、边界组合
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


class TestPenaltyChainSummary:
    def test_betrayal_score_summary_flow(self, ws):
        """背叛→扣分→摘要反映"""
        ws.add_score("agent_0", 20.0)
        ws.record_betrayal("agent_0", 1)
        ws.add_score("agent_0", -20.0)  # 双倍惩罚扣分
        summary = ws.get_agent_summary("agent_0")
        assert summary["betrayal_count"] == 1
        assert summary["score"] == 0.0

    def test_multi_betrayal_status(self, ws):
        """多次背叛 → 计数累积 + 摘要一致"""
        for h in range(5):
            ws.record_betrayal("agent_0", h)
        summary = ws.get_agent_summary("agent_0")
        assert summary["betrayal_count"] == 5
        assert ws.get_betrayal_count("agent_0") == 5


class TestStatusScoreContributionFlow:
    def test_status_and_score_independent(self, ws):
        """状态与积分互不影响"""
        ws.set_agent_status("agent_0", AgentStatus.DEMOTED)
        ws.add_score("agent_0", 8.0)
        assert ws.get_agent_status("agent_0") == AgentStatus.DEMOTED
        assert ws.get_score("agent_0") == 8.0
        assert ws.get_contribution("agent_0") == 8.0

    def test_weight_and_score_flow(self, ws):
        """权重更新 + 积分 → 摘要一致"""
        ws.update_consensus_weight("agent_0", 0.6)
        ws.add_score("agent_0", 5.0)
        summary = ws.get_agent_summary("agent_0")
        assert summary["consensus_weight"] == 0.6
        assert summary["score"] == 5.0


class TestCrossOperationConsistency:
    def test_score_behavior_system_consistency(self, ws):
        """积分+行为+系统状态跨操作一致"""
        ws.add_score("agent_0", 3.0)
        ws.record_action("agent_0", "h1", 2)
        ws.update_system_state(height=2, tx_count=3, online_count=2)
        assert ws.get_score("agent_0") == 3.0
        assert ws._behaviors["agent_0"].last_active_block == 2
        assert ws.get_system_state()["block_height"] == 2

    def test_all_scores_and_summaries(self, ws):
        """get_all_scores 与 get_all_agents_summary 一致"""
        ws.add_score("agent_0", 10.0)
        ws.add_score("agent_1", -5.0)
        scores = ws.get_all_scores()
        summaries = ws.get_all_agents_summary()
        assert scores["agent_0"] == summaries[0]["score"]
        assert scores["agent_1"] == summaries[1]["score"]


class TestEdgeCombos:
    def test_unregistered_all_queries_safe(self, ws):
        """未注册智能体全查询安全（不崩溃）"""
        assert ws.get_public_key("ghost") is None
        assert ws.get_agent_status("ghost") is None
        assert ws.get_contribution("ghost") == 0.0
        assert ws.get_betrayal_count("ghost") == 0
        assert ws.is_registered("ghost") is False

    def test_duplicate_register_after_ops(self, ws):
        """操作后重复注册仍拒绝"""
        ws.add_score("agent_0", 5.0)
        assert ws.register_agent("agent_0", "0x" + "ef" * 32) is False
        assert ws.get_score("agent_0") == 5.0  # 状态未被覆盖

    def test_weight_update_bounds(self, ws):
        """权重边界：0 与 1 均可设置"""
        ws.update_consensus_weight("agent_0", 0.0)
        assert ws.get_consensus_weight("agent_0") == 0.0
        ws.update_consensus_weight("agent_0", 1.0)
        assert ws.get_consensus_weight("agent_0") == 1.0

"""
惩罚智能合约测试
覆盖：三级惩罚机制（警告/降级/封禁）、权限控制、查询接口
"""
import pytest
import sys
sys.path.insert(0, '.')

from blockchain.ledger.world_state import WorldState, AgentStatus
from blockchain.contracts.identity_contract import IdentityContract
from blockchain.contracts.penalty_contract import PenaltyContract


@pytest.fixture
def setup():
    ws = WorldState()
    id_contract = IdentityContract(ws)
    penalty = PenaltyContract(ws, id_contract)
    for i in range(3):
        pk = "04" + "a" * 128
        ws.register_agent(f"agent_{i}", pk)
    return ws, id_contract, penalty


class TestWarningLevel:
    """警告级惩罚"""

    def test_first_betrayal_warning(self, setup):
        ws, id_contract, penalty = setup
        ws.record_betrayal("agent_0", 1)
        result = penalty.apply_penalty("agent_0", "mild")
        assert result["success"] is True
        assert result["level"] == "WARNING"
        assert result["score_penalty"] == -20.0

    def test_warning_deducts_score(self, setup):
        ws, _, penalty = setup
        ws.record_betrayal("agent_0", 1)
        score_before = ws.get_score("agent_0")
        penalty.apply_penalty("agent_0", "mild")
        score_after = ws.get_score("agent_0")
        assert score_after == score_before - 20.0


class TestDemotionLevel:
    """降级级惩罚"""

    def test_demotion_after_30_betrayals(self, setup):
        ws, _, penalty = setup
        for i in range(30):
            ws.record_betrayal("agent_0", i + 1)
        result = penalty.apply_penalty("agent_0", "moderate")
        assert result["success"] is True
        assert result["level"] == "DEMOTED"
        assert result["new_consensus_weight"] == 0.3

    def test_demotion_sets_status(self, setup):
        ws, _, penalty = setup
        for i in range(30):
            ws.record_betrayal("agent_0", i + 1)
        penalty.apply_penalty("agent_0", "moderate")
        status = ws.get_agent_status("agent_0")
        assert status == AgentStatus.DEMOTED


class TestBanLevel:
    """封禁级惩罚"""

    def test_ban_after_50_betrayals(self, setup):
        ws, _, penalty = setup
        for i in range(50):
            ws.record_betrayal("agent_0", i + 1)
        result = penalty.apply_penalty("agent_0", "severe")
        assert result["success"] is True
        assert result["level"] == "BANNED"

    def test_severity_override_triggers_ban(self, setup):
        ws, _, penalty = setup
        ws.record_betrayal("agent_0", 1)
        result = penalty.apply_penalty("agent_0", "severe")
        assert result["level"] == "BANNED"

    def test_banned_agent_weight_zero(self, setup):
        ws, _, penalty = setup
        for i in range(50):
            ws.record_betrayal("agent_0", i + 1)
        penalty.apply_penalty("agent_0", "severe")
        status = ws.get_agent_status("agent_0")
        assert status == AgentStatus.BANNED

    def test_is_banned(self, setup):
        ws, _, penalty = setup
        assert penalty.is_banned("agent_0") is False
        for i in range(50):
            ws.record_betrayal("agent_0", i + 1)
        penalty.apply_penalty("agent_0", "severe")
        assert penalty.is_banned("agent_0") is True


class TestUnregisteredAgent:
    """未注册智能体处理"""

    def test_unregistered_returns_error(self, setup):
        _, _, penalty = setup
        result = penalty.apply_penalty("unknown_agent", "mild")
        assert result["success"] is False
        assert "未注册" in result["error"]


class TestPenaltyHistory:
    """惩罚历史查询"""

    def test_get_penalty_history(self, setup):
        ws, _, penalty = setup
        ws.record_betrayal("agent_0", 1)
        penalty.apply_penalty("agent_0", "mild")
        history = penalty.get_penalty_history("agent_0")
        assert history["agent_id"] == "agent_0"
        assert history["betrayal_count"] >= 1

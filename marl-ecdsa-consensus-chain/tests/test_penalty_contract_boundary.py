"""
PenaltyContract 边界测试（RalphLoop 原子任务 N）
覆盖：三级惩罚（警告/降级/封禁）、未注册处理、封禁检查、惩罚记录
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from blockchain.ledger.world_state import WorldState, AgentStatus
from blockchain.contracts.penalty_contract import PenaltyContract

logging.basicConfig(level=logging.CRITICAL)


@pytest.fixture
def ws():
    state = WorldState()
    for i in range(3):
        state.register_agent(f"agent_{i}", f"0x{'ab' * 32 if i % 2 == 0 else 'cd' * 32}")
    return state


@pytest.fixture
def penalty(ws):
    return PenaltyContract(ws)


class TestApplyPenalty:
    def test_unregistered_agent_returns_error(self, penalty):
        result = penalty.apply_penalty("ghost_agent")
        assert result["success"] is False
        assert "未注册" in result["error"]

    def test_mild_penalty_warning(self, penalty, ws):
        """轻度惩罚 → 警告级：扣 20 积分"""
        result = penalty.apply_penalty("agent_0", severity="mild")
        assert result["level"] == "WARNING"
        assert ws.get_score("agent_0") == -20.0

    def test_moderate_penalty_demotion(self, penalty, ws):
        """中度惩罚 → 降级：共识权重降至 0.3"""
        result = penalty.apply_penalty("agent_0", severity="moderate")
        assert result["level"] == "DEMOTED"
        assert result["new_consensus_weight"] == 0.3
        assert ws.get_agent_status("agent_0") == AgentStatus.DEMOTED

    def test_severe_penalty_ban(self, penalty, ws):
        """重度惩罚 → 封禁：权重归零 + 状态 BANNED"""
        result = penalty.apply_penalty("agent_0", severity="severe")
        assert result["level"] == "BANNED"
        assert ws.get_agent_status("agent_0") == AgentStatus.BANNED


class TestBannedCheck:
    def test_is_banned_after_severe(self, penalty, ws):
        assert penalty.is_banned("agent_0") is False
        penalty.apply_penalty("agent_0", severity="severe")
        assert penalty.is_banned("agent_0") is True

    def test_is_banned_unregistered_false(self, penalty):
        assert penalty.is_banned("ghost_agent") is False

    def test_is_banned_after_warning_false(self, penalty):
        penalty.apply_penalty("agent_0", severity="mild")
        assert penalty.is_banned("agent_0") is False


class TestPenaltyHistory:
    def test_get_penalty_history_registered(self, penalty, ws):
        history = penalty.get_penalty_history("agent_0")
        assert history["agent_id"] == "agent_0"
        assert "betrayal_count" in history

    def test_get_penalty_history_unregistered(self, penalty):
        history = penalty.get_penalty_history("ghost_agent")
        assert history["agent_id"] == "ghost_agent"
        assert history["betrayal_count"] == 0


class TestThresholdAutoLevel:
    def test_betrayal_count_reaches_ban_threshold(self, penalty, ws):
        """背叛次数达到封禁阈值 → 自动封禁（无需 severity）"""
        # 手动设置背叛计数到封禁阈值
        threshold = PenaltyContract.BAN_THRESHOLD
        for _ in range(threshold):
            ws.record_betrayal("agent_1", 1)
        result = penalty.apply_penalty("agent_1")  # 默认 mild，但背叛数已达标
        assert result["level"] == "BANNED"

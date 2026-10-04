"""
更多模块剩余边界测试（RalphLoop 原子任务 DJ）
覆盖：incentive_contract 奖励融合、penalty_contract 分级/历史（此前未单点覆盖）
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from blockchain.ledger.world_state import WorldState, AgentStatus
from blockchain.contracts.incentive_contract import IncentiveContract, ContributionScore
from blockchain.contracts.penalty_contract import PenaltyContract

logging.basicConfig(level=logging.CRITICAL)


@pytest.fixture
def ws():
    state = WorldState()
    for i in range(3):
        state.register_agent(f"agent_{i}", f"0x{'ab' * 32}")
    return state


class TestIncentiveReward:
    def test_bc_reward_lambda_scaling(self, ws):
        """BC 奖励 = λ * 累计积分"""
        contract = IncentiveContract(ws)
        ws.add_score("agent_0", 10.0)
        assert contract.compute_bc_reward("agent_0", lambda_weight=0.1) == 1.0
        assert contract.compute_bc_reward("agent_0", lambda_weight=0.5) == 5.0

    def test_bc_reward_zero_score(self, ws):
        """零积分 → 奖励 0"""
        contract = IncentiveContract(ws)
        assert contract.compute_bc_reward("agent_0") == 0.0

    def test_get_all_bc_rewards(self, ws):
        """批量 BC 奖励"""
        contract = IncentiveContract(ws)
        ws.add_score("agent_0", 10.0)
        ws.add_score("agent_1", 20.0)
        rewards = contract.get_all_bc_rewards(lambda_weight=0.1)
        assert rewards["agent_0"] == 1.0
        assert rewards["agent_1"] == 2.0


class TestPenaltyGrades:
    def test_warning_grade(self, ws):
        """警告级：扣 20 分"""
        penalty = PenaltyContract(ws)
        result = penalty.apply_penalty("agent_0", severity="mild")
        assert result["level"] == "WARNING"
        assert ws.get_score("agent_0") == -20.0

    def test_demotion_grade(self, ws):
        """降级级：权重 0.3"""
        penalty = PenaltyContract(ws)
        result = penalty.apply_penalty("agent_0", severity="moderate")
        assert result["level"] == "DEMOTED"
        assert ws.get_consensus_weight("agent_0") == 0.3

    def test_ban_grade(self, ws):
        """封禁级：状态 BANNED"""
        penalty = PenaltyContract(ws)
        result = penalty.apply_penalty("agent_0", severity="severe")
        assert result["level"] == "BANNED"
        assert ws.get_agent_status("agent_0") == AgentStatus.BANNED


class TestPenaltyQueries:
    def test_is_banned_after_severe(self, ws):
        """封禁后 is_banned True"""
        penalty = PenaltyContract(ws)
        penalty.apply_penalty("agent_0", severity="severe")
        assert penalty.is_banned("agent_0") is True

    def test_is_banned_unregistered(self, ws):
        """未注册 → False"""
        penalty = PenaltyContract(ws)
        assert penalty.is_banned("ghost") is False

    def test_penalty_history_structure(self, ws):
        """惩罚历史含计数"""
        penalty = PenaltyContract(ws)
        ws.record_betrayal("agent_0", 1)
        history = penalty.get_penalty_history("agent_0")
        assert history["agent_id"] == "agent_0"
        assert history["betrayal_count"] == 1

    def test_penalty_history_unregistered_default(self, ws):
        """未注册历史 → 默认零值"""
        penalty = PenaltyContract(ws)
        history = penalty.get_penalty_history("ghost")
        assert history["betrayal_count"] == 0

"""
IncentiveContract 边界测试（RalphLoop 原子任务 L）
覆盖：贡献度评分、结算规则（惩罚/基础/加成）、空输入、排行榜
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from blockchain.ledger.world_state import WorldState
from blockchain.contracts.incentive_contract import (
    IncentiveContract, ContributionScore,
)

logging.basicConfig(level=logging.CRITICAL)


@pytest.fixture
def ws():
    state = WorldState()
    for i in range(3):
        state.register_agent(f"agent_{i}", f"0x{'ab' * 32 if i % 2 == 0 else 'cd' * 32}")
    return state


@pytest.fixture
def contract(ws):
    return IncentiveContract(ws)


class TestComputeContribution:
    def test_cooperate_scores(self, contract):
        cs = contract.compute_contribution("agent_0", 0.8, did_cooperate=True, did_betray=False)
        assert cs.cooperation_score == 1.0
        assert cs.compliance_score == 1.0
        assert 0.0 <= cs.task_score <= 1.0

    def test_betray_scores(self, contract):
        cs = contract.compute_contribution("agent_0", 0.8, did_cooperate=False, did_betray=True)
        assert cs.cooperation_score == 0.0
        assert cs.compliance_score == 0.0

    def test_neutral_cooperation_score(self, contract):
        cs = contract.compute_contribution("agent_0", 0.5, did_cooperate=False, did_betray=False)
        assert cs.cooperation_score == 0.5

    def test_env_reward_clamped(self, contract):
        cs_high = contract.compute_contribution("agent_0", 5.0, False, False)
        cs_low = contract.compute_contribution("agent_0", -5.0, False, False)
        assert cs_high.task_score == 1.0
        assert cs_low.task_score == 0.0


class TestSettleRewards:
    def test_empty_scores_returns_empty(self, contract):
        assert contract.settle_rewards(1, []) == {}

    def test_betrayal_penalty(self, contract):
        """背叛 → 双倍基础奖励惩罚（-20）"""
        cs = ContributionScore("agent_0", task_score=0.5, cooperation_score=0.0, compliance_score=0.0)
        deltas = contract.settle_rewards(1, [cs])
        assert deltas["agent_0"] == -20.0  # -BASE_REWARD * 2

    def test_honest_base_reward(self, contract):
        """诚实 → 基础奖励（+10）"""
        cs = ContributionScore("agent_0", task_score=0.5, cooperation_score=1.0, compliance_score=1.0)
        deltas = contract.settle_rewards(2, [cs])
        assert deltas["agent_0"] >= 10.0  # 基础 + 可能加成

    def test_settlement_history_recorded(self, contract):
        cs = ContributionScore("agent_0", task_score=0.5, cooperation_score=1.0, compliance_score=1.0)
        contract.settle_rewards(5, [cs])
        # get_settlement_history(block_height) 按区块高度查询
        assert len(contract.get_settlement_history(5)) == 1


class TestScoreWeighting:
    def test_weighted_score_combination(self, contract):
        """加权综合分 = 0.4*任务 + 0.35*合作 + 0.25*合规"""
        cs = ContributionScore("agent_0", task_score=1.0, cooperation_score=1.0, compliance_score=1.0)
        assert cs.weighted_score == pytest.approx(1.0)

    def test_weighted_score_betrayal_low(self, contract):
        cs = ContributionScore("agent_0", task_score=1.0, cooperation_score=0.0, compliance_score=0.0)
        assert cs.weighted_score < 0.5  # 背叛拉低综合分


class TestLeaderboard:
    def test_get_leaderboard(self, contract, ws):
        contract.compute_contribution("agent_0", 0.8, True, False)
        contract.compute_contribution("agent_1", 0.5, False, False)
        contract.compute_contribution("agent_2", 0.2, False, True)
        scores = [
            contract.compute_contribution("agent_0", 0.8, True, False),
            contract.compute_contribution("agent_1", 0.5, False, False),
            contract.compute_contribution("agent_2", 0.2, False, True),
        ]
        contract.settle_rewards(10, scores)
        board = contract.get_leaderboard()
        assert isinstance(board, list)
        assert len(board) == 3

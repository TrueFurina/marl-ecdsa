"""
激励结算智能合约测试
覆盖：贡献度量化、激励结算规则、BC奖励融合、排行榜
"""
import pytest
import sys
sys.path.insert(0, '.')

from blockchain.ledger.world_state import WorldState
from blockchain.contracts.incentive_contract import IncentiveContract, ContributionScore


@pytest.fixture
def world_state():
    ws = WorldState()
    for i in range(3):
        pk = "04" + "a" * 128  # 模拟公钥
        ws.register_agent(f"agent_{i}", pk)
    return ws


@pytest.fixture
def incentive_contract(world_state):
    return IncentiveContract(world_state)


class TestContributionScore:
    """贡献度评分计算"""

    def test_weighted_score_formula(self):
        """加权综合贡献度 = 0.4*task + 0.35*coop + 0.25*compliance"""
        cs = ContributionScore("a0", task_score=1.0, cooperation_score=1.0, compliance_score=1.0)
        assert cs.weighted_score == pytest.approx(1.0)

    def test_weighted_score_partial(self):
        cs = ContributionScore("a0", task_score=0.5, cooperation_score=0.8, compliance_score=1.0)
        expected = 0.4 * 0.5 + 0.35 * 0.8 + 0.25 * 1.0
        assert cs.weighted_score == pytest.approx(expected)

    def test_weighted_score_zero(self):
        cs = ContributionScore("a0", task_score=0, cooperation_score=0, compliance_score=0)
        assert cs.weighted_score == 0.0


class TestComputeContribution:
    """贡献度计算"""

    def test_cooperator_full_scores(self, incentive_contract):
        cs = incentive_contract.compute_contribution(
            "agent_0", env_reward=0.8, did_cooperate=True, did_betray=False
        )
        assert cs.task_score == 0.8
        assert cs.cooperation_score == 1.0
        assert cs.compliance_score == 1.0

    def test_betrayer_zero_coop(self, incentive_contract):
        cs = incentive_contract.compute_contribution(
            "agent_0", env_reward=0.5, did_cooperate=False, did_betray=True
        )
        assert cs.cooperation_score == 0.0
        assert cs.compliance_score == 0.0

    def test_neutral_half_coop(self, incentive_contract):
        cs = incentive_contract.compute_contribution(
            "agent_0", env_reward=0.5, did_cooperate=False, did_betray=False
        )
        assert cs.cooperation_score == 0.5
        assert cs.compliance_score == 1.0

    def test_env_reward_clamped(self, incentive_contract):
        """环境奖励超出[0,1]范围时被截断"""
        cs_high = incentive_contract.compute_contribution("a0", env_reward=2.0, did_cooperate=True, did_betray=False)
        assert cs_high.task_score == 1.0
        cs_neg = incentive_contract.compute_contribution("a0", env_reward=-1.0, did_cooperate=True, did_betray=False)
        assert cs_neg.task_score == 0.0


class TestSettleRewards:
    """激励结算规则"""

    def test_honest_agent_gets_base_reward(self, incentive_contract):
        cs = incentive_contract.compute_contribution("agent_0", 0.5, True, False)
        deltas = incentive_contract.settle_rewards(1, [cs])
        assert deltas["agent_0"] > 0  # 基础奖励+可能加成
        assert deltas["agent_0"] >= 10.0  # 至少基础奖励

    def test_betrayer_gets_penalty(self, incentive_contract):
        cs = incentive_contract.compute_contribution("agent_0", 0.5, False, True)
        deltas = incentive_contract.settle_rewards(1, [cs])
        assert deltas["agent_0"] < 0  # 双倍惩罚
        assert deltas["agent_0"] == -20.0  # -10 * 2

    def test_top_contributor_gets_bonus(self, incentive_contract):
        """贡献度前30%获得额外加成"""
        scores = []
        for i in range(3):
            cs = incentive_contract.compute_contribution(
                f"agent_{i}", env_reward=0.9 - i * 0.1, did_cooperate=True, did_betray=False
            )
            scores.append(cs)
        deltas = incentive_contract.settle_rewards(1, scores)
        # agent_0 贡献度最高，应有加成
        assert deltas["agent_0"] > deltas["agent_2"]
        assert deltas["agent_0"] > 10.0  # 基础+加成

    def test_empty_scores_returns_empty(self, incentive_contract):
        deltas = incentive_contract.settle_rewards(1, [])
        assert deltas == {}

    def test_settlement_history_recorded(self, incentive_contract):
        cs = incentive_contract.compute_contribution("agent_0", 0.5, True, False)
        incentive_contract.settle_rewards(5, [cs])
        history = incentive_contract.get_settlement_history(5)
        assert len(history) == 1
        assert history[0]["agent_id"] == "agent_0"
        assert "weighted_score" in history[0]

    def test_cooperation_betrayal_mix(self, incentive_contract):
        """混合场景：2合作1背叛"""
        cs_coop1 = incentive_contract.compute_contribution("agent_0", 0.7, True, False)
        cs_coop2 = incentive_contract.compute_contribution("agent_1", 0.6, True, False)
        cs_betray = incentive_contract.compute_contribution("agent_2", 0.1, False, True)
        deltas = incentive_contract.settle_rewards(1, [cs_coop1, cs_coop2, cs_betray])
        assert deltas["agent_0"] > 0
        assert deltas["agent_1"] > 0
        assert deltas["agent_2"] < 0


class TestBCReward:
    """区块链奖励融合"""

    def test_compute_bc_reward(self, incentive_contract):
        bc_reward = incentive_contract.compute_bc_reward("agent_0", lambda_weight=0.1)
        # agent_0 初始score为0（刚注册）
        assert bc_reward == 0.0

    def test_bc_reward_after_settlement(self, incentive_contract):
        cs = incentive_contract.compute_contribution("agent_0", 0.8, True, False)
        incentive_contract.settle_rewards(1, [cs])
        bc_reward = incentive_contract.compute_bc_reward("agent_0", lambda_weight=0.1)
        assert bc_reward > 0

    def test_get_all_bc_rewards(self, incentive_contract):
        rewards = incentive_contract.get_all_bc_rewards(lambda_weight=0.1)
        assert len(rewards) == 3
        assert all(v >= 0 for v in rewards.values())


class TestQueryInterface:
    """查询接口"""

    def test_get_leaderboard(self, incentive_contract):
        cs1 = incentive_contract.compute_contribution("agent_0", 0.9, True, False)
        cs2 = incentive_contract.compute_contribution("agent_1", 0.3, True, False)
        incentive_contract.settle_rewards(1, [cs1, cs2])
        board = incentive_contract.get_leaderboard()
        assert len(board) >= 2
        assert board[0][1] >= board[1][1]  # 降序

    def test_get_stats(self, incentive_contract):
        cs = incentive_contract.compute_contribution("agent_0", 0.5, True, False)
        incentive_contract.settle_rewards(1, [cs])
        stats = incentive_contract.get_stats()
        assert stats["total_agents"] == 3
        assert stats["settled_blocks"] == 1
        assert "avg_score" in stats

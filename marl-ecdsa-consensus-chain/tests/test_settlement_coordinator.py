"""
SettlementCoordinator 子组件独立测试
覆盖：贡献度评分、激励结算、奖励融合、积分查询、模拟结算、P2-C双源修复
"""
import pytest
import sys
import tempfile
import shutil

sys.path.insert(0, '.')

from marl.integration.settlement_coordinator import SettlementCoordinator
from blockchain.ledger.world_state import WorldState
from blockchain.contracts.incentive_contract import IncentiveContract, ContributionScore
from blockchain.contracts.identity_contract import IdentityContract


@pytest.fixture
def settlement_with_contract():
    """带真实 IncentiveContract 的 SettlementCoordinator"""
    ws = WorldState()
    id_contract = IdentityContract(ws)
    incentive = IncentiveContract(ws)

    # 注册智能体
    for i in range(3):
        ws.register_agent(f"agent_{i}", f"pk_{i}")

    coordinator = SettlementCoordinator(
        incentive_contract=incentive,
        n_agents=3,
        lambda_weight=0.1,
    )
    yield coordinator, ws, incentive


@pytest.fixture
def settlement_ablate():
    """无 IncentiveContract 的 ablate 模式"""
    return SettlementCoordinator(
        incentive_contract=None,
        n_agents=3,
        lambda_weight=0.1,
    )


AGENT_IDS = ["agent_0", "agent_1", "agent_2"]


class TestSettlementCoordinatorInit:
    """初始化测试"""

    def test_init_with_contract(self, settlement_with_contract):
        """有 incentive_contract 时初始化"""
        coord, ws, ic = settlement_with_contract
        assert coord.incentive_contract is not None
        assert coord.lambda_weight == 0.1
        assert len(coord._bc_scores) == 3
        assert len(coord._bc_rewards) == 3

    def test_init_ablate_mode(self, settlement_ablate):
        """ablate 模式初始化"""
        assert settlement_ablate.incentive_contract is None
        assert settlement_ablate.lambda_weight == 0.1

    def test_init_scores_zero(self, settlement_with_contract):
        """初始积分应为 0"""
        coord, _, _ = settlement_with_contract
        for aid in AGENT_IDS:
            assert coord._bc_scores[aid] == 0.0
            assert coord._bc_rewards[aid] == 0.0


class TestComputeContributionScores:
    """贡献度评分构造"""

    def test_all_cooperate(self, settlement_with_contract):
        """所有智能体合作 → 贡献度评分"""
        coord, _, _ = settlement_with_contract
        env_rewards = [-2.0, -1.5, -1.0]
        coop_results = {aid: (True, False) for aid in AGENT_IDS}

        scores = coord.compute_contribution_scores(AGENT_IDS, env_rewards, coop_results)

        assert len(scores) == 3
        for cs in scores:
            assert isinstance(cs, ContributionScore)
            assert cs.agent_id in AGENT_IDS
            assert cs.cooperation_score == 1.0  # did_cooperate=True
            assert cs.compliance_score == 1.0   # did_betray=False

    def test_one_betray(self, settlement_with_contract):
        """一个背叛智能体的评分"""
        coord, _, _ = settlement_with_contract
        env_rewards = [-2.0, -1.5, -1.0]
        coop_results = {
            "agent_0": (True, False),
            "agent_1": (False, True),   # 背叛
            "agent_2": (True, False),
        }

        scores = coord.compute_contribution_scores(AGENT_IDS, env_rewards, coop_results)
        # agent_1 背叛 → compliance_score=0.0, cooperation_score=0.0
        assert scores[1].compliance_score == 0.0
        assert scores[1].cooperation_score == 0.0

    def test_ablate_mode_scoring(self, settlement_ablate):
        """ablate 模式（无合约）模拟评分"""
        coord = settlement_ablate
        env_rewards = [-2.0, -1.5, -1.0]
        coop_results = {aid: (True, False) for aid in AGENT_IDS}

        scores = coord.compute_contribution_scores(AGENT_IDS, env_rewards, coop_results)
        assert len(scores) == 3
        # 模拟模式应构造 ContributionScore（无合约调用）
        for cs in scores:
            assert isinstance(cs, ContributionScore)
            assert cs.agent_id in AGENT_IDS

    def test_env_reward_normalization(self, settlement_with_contract):
        """环境奖励归一化到 [0, 1]"""
        coord, _, ic = settlement_with_contract
        # P1-2 后归一化区间为 [-1.5, 2.0]（config.json blockchain.env_reward_normalization），
        # 旧注释的 (env_r+5)/10 是已被替换的旧公式，仅更新说明、不改断言：
        #   env_reward=-5 → (−5−(−1.5))/3.5 = −1.0  → 下界裁剪为 0.0
        #   env_reward=0  → (0−(−1.5))/3.5  = 0.4286
        #   env_reward=5  → (5−(−1.5))/3.5  = 1.857  → 上界裁剪为 1.0
        env_rewards = [-5.0, 0.0, 5.0]
        coop_results = {aid: (True, False) for aid in AGENT_IDS}

        scores = coord.compute_contribution_scores(AGENT_IDS, env_rewards, coop_results)

        # 检查 task_score（由 incentive_contract.compute_contribution 内部归一化）
        assert scores[0].task_score >= 0.0  # 归一化后 >= 0
        assert scores[2].task_score >= 0.0

    def test_neutral_behavior_score(self, settlement_ablate):
        """中性行为（未合作也未背叛）的评分"""
        coord = settlement_ablate
        env_rewards = [-2.0, -1.5, -1.0]
        coop_results = {
            "agent_0": (False, False),  # 中性
            "agent_1": (True, False),
            "agent_2": (False, True),
        }

        scores = coord.compute_contribution_scores(AGENT_IDS, env_rewards, coop_results)
        # ablate: 中性 → cooperation_score=0.5, compliance_score=1.0
        assert scores[0].cooperation_score == 0.5  # 中性
        assert scores[0].compliance_score == 1.0    # 不背叛=合规


class TestSettle:
    """激励结算"""

    def test_settle_with_contract(self, settlement_with_contract):
        """有合约时结算"""
        coord, ws, ic = settlement_with_contract
        env_rewards = [-2.0, -1.5, -1.0]
        coop_results = {aid: (True, False) for aid in AGENT_IDS}

        scores = coord.compute_contribution_scores(AGENT_IDS, env_rewards, coop_results)
        deltas = coord.settle(episode=0, scores=scores)

        assert len(deltas) == 3
        for aid in AGENT_IDS:
            assert aid in deltas
            assert isinstance(deltas[aid], float)

    def test_settle_ablate_mode(self, settlement_ablate):
        """ablate 模式模拟结算"""
        coord = settlement_ablate
        env_rewards = [-2.0, -1.5, -1.0]
        coop_results = {aid: (True, False) for aid in AGENT_IDS}

        scores = coord.compute_contribution_scores(AGENT_IDS, env_rewards, coop_results)
        deltas = coord.settle(episode=0, scores=scores)

        assert len(deltas) == 3
        # 模拟结算：合作 → delta = 10 + 5*weighted_score
        for aid in AGENT_IDS:
            assert deltas[aid] > 0, f"{aid} 合作时模拟结算应为正值"

    def test_settle_betrayal_penalty(self, settlement_ablate):
        """背叛惩罚：温和策略（delta=-8）"""
        coord = settlement_ablate
        env_rewards = [-2.0, -1.5, -1.0]
        coop_results = {
            "agent_0": (False, True),   # 背叛
            "agent_1": (True, False),
            "agent_2": (True, False),
        }

        scores = coord.compute_contribution_scores(AGENT_IDS, env_rewards, coop_results)
        deltas = coord.settle(episode=0, scores=scores)

        assert deltas["agent_0"] == -8.0, "背叛应温和惩罚 -8"
        assert deltas["agent_1"] > 0
        assert deltas["agent_2"] > 0


class TestUpdateRewardsAndScores:
    """积分更新（P2-C修复验证）"""

    def test_normal_mode_no_bc_scores_update(self, settlement_with_contract):
        """正常模式：_bc_scores 不更新（WorldState为唯一源）"""
        coord, ws, ic = settlement_with_contract
        deltas = {"agent_0": 5.0, "agent_1": 3.0, "agent_2": 1.0}

        coord.update_rewards_and_scores(deltas)

        # bc_rewards 应更新
        assert coord._bc_rewards["agent_0"] == 5.0
        assert coord._bc_rewards["agent_1"] == 3.0

        # _bc_scores 不更新（P2-C: 正常模式由 WorldState 管理）
        assert coord._bc_scores["agent_0"] == 0.0  # 未变化
        assert coord._bc_scores["agent_1"] == 0.0

    def test_ablate_mode_bc_scores_update(self, settlement_ablate):
        """ablate 模式：_bc_scores 正常累积（唯一源）"""
        coord = settlement_ablate
        deltas = {"agent_0": 5.0, "agent_1": 3.0, "agent_2": 1.0}

        coord.update_rewards_and_scores(deltas)

        # _bc_scores 应累积
        assert coord._bc_scores["agent_0"] == 5.0
        assert coord._bc_scores["agent_1"] == 3.0
        assert coord._bc_scores["agent_2"] == 1.0

        # bc_rewards 也更新
        assert coord._bc_rewards["agent_0"] == 5.0

    def test_cumulative_scores_ablate(self, settlement_ablate):
        """ablate 模式多次累积"""
        coord = settlement_ablate
        for ep in range(3):
            deltas = {"agent_0": 2.0, "agent_1": 1.0, "agent_2": 0.5}
            coord.update_rewards_and_scores(deltas)

        assert coord._bc_scores["agent_0"] == 6.0  # 3 * 2.0
        assert coord._bc_scores["agent_1"] == 3.0  # 3 * 1.0


class TestComputeTotalReward:
    """奖励融合公式"""

    def test_basic_fusion(self, settlement_ablate):
        """total = env + λ * bc_reward"""
        coord = settlement_ablate
        coord.update_rewards_and_scores({"agent_0": 5.0, "agent_1": 3.0, "agent_2": 1.0})

        # agent_0: total = -2.0 + 0.1 * 5.0 = -1.5
        result = coord.compute_total_reward("agent_0", -2.0)
        assert result == pytest.approx(-2.0 + 0.1 * 5.0, abs=0.01)

    def test_lambda_weight_effect(self):
        """不同 λ 权重影响"""
        coord = SettlementCoordinator(
            incentive_contract=None, n_agents=3, lambda_weight=0.2
        )
        coord.update_rewards_and_scores({"agent_0": 5.0, "agent_1": 0, "agent_2": 0})

        result = coord.compute_total_reward("agent_0", -2.0)
        assert result == pytest.approx(-2.0 + 0.2 * 5.0, abs=0.01)

    def test_reward_clipping(self):
        """bc_reward 裁剪到 [-20, 20]"""
        coord = SettlementCoordinator(
            incentive_contract=None, n_agents=3, lambda_weight=0.1
        )
        # 极大 bc_reward: 100 → 裁剪到 20
        coord.update_rewards_and_scores({"agent_0": 100.0, "agent_1": 0, "agent_2": 0})
        result = coord.compute_total_reward("agent_0", -2.0)
        assert result == pytest.approx(-2.0 + 0.1 * 20.0, abs=0.01)  # 裁剪后

    def test_negative_bc_reward_clipping(self):
        """负 bc_reward 裁剪到 -20"""
        coord = SettlementCoordinator(
            incentive_contract=None, n_agents=3, lambda_weight=0.1
        )
        coord.update_rewards_and_scores({"agent_0": -50.0, "agent_1": 0, "agent_2": 0})
        result = coord.compute_total_reward("agent_0", -2.0)
        assert result == pytest.approx(-2.0 + 0.1 * (-20.0), abs=0.01)  # 裁剪后

    def test_get_all_total_rewards(self, settlement_ablate):
        """批量计算融合奖励"""
        coord = settlement_ablate
        coord.update_rewards_and_scores({"agent_0": 5.0, "agent_1": 3.0, "agent_2": 1.0})

        env_rewards = [-2.0, -1.5, -1.0]
        results = coord.get_all_total_rewards(env_rewards, AGENT_IDS)
        assert len(results) == 3
        # agent_0: -2.0 + 0.1*5.0 = -1.5
        assert results[0] == pytest.approx(-1.5, abs=0.01)


class TestGetBcScores:
    """积分查询（P2-C: WorldState 为权威源）"""

    def test_get_bc_scores_with_contract(self, settlement_with_contract):
        """有合约时 get_bc_scores 委托 WorldState"""
        coord, ws, ic = settlement_with_contract
        # 先结算一次让 WorldState 有积分数据
        env_rewards = [-2.0, -1.5, -1.0]
        coop_results = {aid: (True, False) for aid in AGENT_IDS}
        scores = coord.compute_contribution_scores(AGENT_IDS, env_rewards, coop_results)
        deltas = coord.settle(episode=0, scores=scores)
        coord.update_rewards_and_scores(deltas)

        # get_bc_scores 应委托 WorldState
        bc_scores = coord.get_bc_scores()
        assert len(bc_scores) == 3
        # 正常模式下 _bc_scores 为 0（不更新），WorldState 才是权威源
        # 所以 get_bc_scores 应返回 WorldState 的积分（非零）
        # 注意：这里 settle_rewards 已更新 WorldState
        for aid in AGENT_IDS:
            assert aid in bc_scores

    def test_get_bc_scores_ablate_mode(self, settlement_ablate):
        """ablate 模式 get_bc_scores 返回 _bc_scores fallback"""
        coord = settlement_ablate
        coord.update_rewards_and_scores({"agent_0": 5.0, "agent_1": 3.0, "agent_2": 1.0})

        bc_scores = coord.get_bc_scores()
        assert bc_scores["agent_0"] == 5.0
        assert bc_scores["agent_1"] == 3.0


class TestGetBcRewards:
    """本回合积分变化查询"""

    def test_get_bc_rewards_after_update(self, settlement_ablate):
        """更新后 bc_rewards 应反映变化"""
        coord = settlement_ablate
        coord.update_rewards_and_scores({"agent_0": 5.0, "agent_1": 3.0, "agent_2": 1.0})

        rewards = coord.get_bc_rewards()
        assert rewards["agent_0"] == 5.0
        assert rewards["agent_1"] == 3.0
        assert rewards["agent_2"] == 1.0


class TestGetStats:
    """统计接口"""

    def test_get_stats_structure(self, settlement_with_contract):
        """get_stats 返回完整结构"""
        coord, _, _ = settlement_with_contract
        stats = coord.get_stats()
        assert 'bc_scores' in stats
        assert 'bc_rewards' in stats
        assert 'lambda_weight' in stats

    def test_get_stats_lambda_weight(self):
        """get_stats 应包含 lambda_weight"""
        coord = SettlementCoordinator(
            incentive_contract=None, n_agents=3, lambda_weight=0.2
        )
        stats = coord.get_stats()
        assert stats['lambda_weight'] == 0.2


class TestSimulateSettlement:
    """模拟结算（ablate 模式）"""

    def test_cooperation_reward(self):
        """合作奖励：10 + 5 * weighted_score"""
        coord = SettlementCoordinator(
            incentive_contract=None, n_agents=3, lambda_weight=0.1
        )
        # weighted_score = 0.40*task + 0.35*coop + 0.25*comply
        # agent_0: 0.40*0.5 + 0.35*1.0 + 0.25*1.0 = 0.20+0.35+0.25 = 0.80
        scores = [
            ContributionScore("agent_0", 0.5, 1.0, 1.0),  # ws=0.80
            ContributionScore("agent_1", 0.3, 1.0, 1.0),
            ContributionScore("agent_2", 0.5, 0.5, 1.0),
        ]
        deltas = coord._simulate_settlement(scores)
        # agent_0: 10 + 5 * 0.80 = 14.0
        assert deltas["agent_0"] == pytest.approx(10.0 + 5.0 * 0.80, abs=0.01)

    def test_betrayal_penalty(self):
        """背叛惩罚：-8.0（温和策略）"""
        coord = SettlementCoordinator(
            incentive_contract=None, n_agents=3, lambda_weight=0.1
        )
        scores = [
            ContributionScore("agent_0", 0.5, 0.0, 0.0),  # 背叛
            ContributionScore("agent_1", 0.3, 1.0, 1.0),   # 合作
        ]
        deltas = coord._simulate_settlement(scores)
        assert deltas["agent_0"] == -8.0
        assert deltas["agent_1"] > 0

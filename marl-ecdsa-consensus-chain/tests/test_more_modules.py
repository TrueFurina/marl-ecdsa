"""
更多模块剩余边界测试（RalphLoop 原子任务 CV）
覆盖：consensus_shaper 统计、incentive_contract 结算边界（此前未单点覆盖）
通过标准：新增 ≥6 项测试全过
"""
import logging

import numpy as np
import pytest

from marl.integration.consensus_shaper import ConsensusRewardShaper
from blockchain.ledger.world_state import WorldState
from blockchain.contracts.incentive_contract import IncentiveContract, ContributionScore

logging.basicConfig(level=logging.CRITICAL)


def _obs(n=3, n_lm=3):
    lm = np.random.rand(n, n_lm, 2) * 0.8 + 0.1
    rows = []
    for i in range(n):
        rows.append(np.array([0.1, 0.1, 0.5, 0.5] + lm[i].flatten().tolist()))
    return rows


class TestShaperStats:
    def test_get_stats_after_steps(self):
        """多次塑形后统计累计"""
        shaper = ConsensusRewardShaper(n_agents=3)
        obs = _obs(3)
        for _ in range(3):
            shaper.shape_reward(obs, obs, [0, 0, 0], ["a0", "a1", "a2"])
        stats = shaper.get_stats()
        assert stats.get('step_count', 0) == 3

    def test_get_stats_fields(self):
        """get_stats 含关键统计字段"""
        shaper = ConsensusRewardShaper(n_agents=3)
        obs = _obs(3)
        shaper.shape_reward(obs, obs, [0, 0, 0], ["a0", "a1", "a2"],
                            verification_status=[True, True, True],
                            cooperation_status={"a0": True, "a1": True, "a2": True})
        stats = shaper.get_stats()
        assert 'total_verification_bonus' in stats
        assert 'total_cooperation_bonus' in stats
        assert 'total_consensus_bonus' in stats

    def test_get_stats_values_positive(self):
        """验证+合作奖励统计为正"""
        shaper = ConsensusRewardShaper(n_agents=3)
        obs = _obs(3)
        shaper.shape_reward(obs, obs, [0, 0, 0], ["a0", "a1", "a2"],
                            verification_status=[True, True, True],
                            cooperation_status={"a0": True, "a1": True, "a2": True})
        stats = shaper.get_stats()
        assert stats['total_verification_bonus'] > 0
        assert stats['total_cooperation_bonus'] > 0


class TestIncentiveSettlement:
    def test_settlement_rank_bonus(self):
        """前 30% 排名获得梯度加成"""
        ws = WorldState()
        for i in range(4):
            ws.register_agent(f"agent_{i}", f"0x{'ab' * 32}")
        contract = IncentiveContract(ws)
        scores = [
            ContributionScore("agent_0", 1.0, 1.0, 1.0),  # 最高分
            ContributionScore("agent_1", 0.8, 1.0, 1.0),
            ContributionScore("agent_2", 0.5, 1.0, 1.0),
            ContributionScore("agent_3", 0.2, 1.0, 1.0),
        ]
        deltas = contract.settle_rewards(1, scores)
        # 排名1 的加成 ≥ 排名2 的加成（top_n = max(1, 4*0.3)=1 → 仅排名1 有加成）
        assert deltas["agent_0"] >= deltas["agent_1"]

    def test_settlement_betrayal_penalty(self):
        """背叛惩罚：-BASE_REWARD * 2"""
        ws = WorldState()
        ws.register_agent("agent_0", "0x" + "ab" * 32)
        contract = IncentiveContract(ws)
        scores = [ContributionScore("agent_0", 0.5, 0.0, 0.0)]  # 背叛
        deltas = contract.settle_rewards(1, scores)
        assert deltas["agent_0"] == -20.0

    def test_settlement_history_query(self):
        """结算历史按区块查询"""
        ws = WorldState()
        ws.register_agent("agent_0", "0x" + "ab" * 32)
        contract = IncentiveContract(ws)
        scores = [ContributionScore("agent_0", 0.5, 1.0, 1.0)]
        contract.settle_rewards(5, scores)
        history = contract.get_settlement_history(5)
        assert len(history) == 1
        assert history[0]["agent_id"] == "agent_0"

    def test_weighted_score_formula(self):
        """加权分 = 0.4*任务 + 0.35*合作 + 0.25*合规"""
        cs = ContributionScore("agent_0", 1.0, 1.0, 1.0)
        assert cs.weighted_score == pytest.approx(1.0)
        cs2 = ContributionScore("agent_0", 1.0, 0.0, 0.0)
        assert cs2.weighted_score == pytest.approx(0.4)


class TestIncentiveEdge:
    def test_leaderboard_sorted(self):
        """排行榜按分数降序"""
        ws = WorldState()
        for i in range(3):
            ws.register_agent(f"agent_{i}", f"0x{'ab' * 32}")
        contract = IncentiveContract(ws)
        scores = [
            ContributionScore("agent_0", 1.0, 1.0, 1.0),
            ContributionScore("agent_1", 0.5, 1.0, 1.0),
            ContributionScore("agent_2", 0.2, 1.0, 1.0),
        ]
        contract.settle_rewards(1, scores)
        board = contract.get_leaderboard()
        vals = [s for _, s in board]
        assert vals == sorted(vals, reverse=True)  # 降序

    def test_settlement_score_updated(self):
        """结算后 WorldState 积分更新"""
        ws = WorldState()
        ws.register_agent("agent_0", "0x" + "ab" * 32)
        contract = IncentiveContract(ws)
        scores = [ContributionScore("agent_0", 0.5, 1.0, 1.0)]
        contract.settle_rewards(1, scores)
        assert ws.get_score("agent_0") >= 10.0  # 基础奖励

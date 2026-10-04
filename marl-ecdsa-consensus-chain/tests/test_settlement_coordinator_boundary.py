"""
SettlementCoordinator 边界测试（RalphLoop 原子任务 F）
覆盖：贡献评分构造、结算、奖励融合、无合约模拟模式、边界输入
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from marl.integration.settlement_coordinator import SettlementCoordinator

logging.basicConfig(level=logging.CRITICAL)


class TestComputeContributionScores:
    def test_scores_without_contract(self):
        """无激励合约 → 模拟模式，评分含三分量"""
        sc = SettlementCoordinator(n_agents=3, lambda_weight=0.1)
        scores = sc.compute_contribution_scores(
            ["a0", "a1", "a2"], [1.0, 0.0, -1.0],
            {"a0": (True, False), "a1": (False, False), "a2": (False, True)},
        )
        assert len(scores) == 3
        for cs in scores:
            assert 0.0 <= cs.task_score <= 1.0
            assert 0.0 <= cs.cooperation_score <= 1.0
            assert 0.0 <= cs.compliance_score <= 1.0

    def test_scores_empty_coop_results_default(self):
        """空 coop_results → 默认 (False, False)"""
        sc = SettlementCoordinator(n_agents=3)
        scores = sc.compute_contribution_scores(["a0"], [1.0], {})
        assert scores[0].cooperation_score == 0.5  # 中性默认

    def test_betrayal_penalizes_compliance(self):
        """背叛 → compliance_score 归零"""
        sc = SettlementCoordinator(n_agents=3)
        scores = sc.compute_contribution_scores(
            ["a0"], [1.0], {"a0": (False, True)},
        )
        assert scores[0].compliance_score == 0.0

    def test_env_reward_clamped_to_unit(self):
        """环境奖励越界 → 归一化截断到 [0,1]"""
        sc = SettlementCoordinator(n_agents=3)
        scores = sc.compute_contribution_scores(
            ["a0", "a1"], [100.0, -100.0],
            {"a0": (True, False), "a1": (False, False)},
        )
        assert scores[0].task_score <= 1.0
        assert scores[1].task_score >= 0.0


class TestTotalReward:
    def test_compute_total_reward_without_bc(self):
        """λ=0 → 总奖励 = 环境奖励"""
        sc = SettlementCoordinator(n_agents=3, lambda_weight=0.0)
        assert sc.compute_total_reward("a0", env_reward=5.0) == 5.0

    def test_compute_total_reward_returns_float(self):
        sc = SettlementCoordinator(n_agents=3, lambda_weight=0.1)
        total = sc.compute_total_reward("a0", env_reward=1.0)
        assert isinstance(total, float)

    def test_get_all_total_rewards_length(self):
        sc = SettlementCoordinator(n_agents=3)
        rewards = sc.get_all_total_rewards([1.0, 2.0, 3.0], ["a0", "a1", "a2"])
        assert len(rewards) == 3


class TestScoresAndStats:
    def test_update_rewards_and_scores(self):
        sc = SettlementCoordinator(n_agents=3)
        sc.update_rewards_and_scores({"a0": 2.0, "a1": -1.0})
        assert sc.get_bc_rewards()["a0"] == 2.0
        assert sc.get_bc_rewards()["a1"] == -1.0

    def test_get_stats(self):
        sc = SettlementCoordinator(n_agents=3)
        sc.compute_contribution_scores(["a0"], [1.0], {})
        stats = sc.get_stats()
        assert isinstance(stats, dict)
        assert "lambda_weight" in stats or len(stats) > 0

    def test_bc_scores_initialized_for_all_agents(self):
        sc = SettlementCoordinator(n_agents=3)
        assert len(sc.get_bc_scores()) == 3

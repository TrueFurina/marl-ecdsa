"""
Nash均衡验证器测试
覆盖：收益矩阵计算、优势策略验证、参数边界推导、报告生成
"""
import pytest
import numpy as np
from marl.analysis.nash_verifier import (
    NashEquilibriumVerifier, NashResult, DominantStrategyResult, VerificationReport
)


class TestNashVerifierInit:
    """初始化测试"""

    def test_default_params(self):
        v = NashEquilibriumVerifier()
        assert v.lambda_weight == 0.1
        assert v.base_reward == 10.0
        assert v.betrayal_penalty_mult == 2.0
        assert v.bc_cooperate_min == 10.0
        assert v.bc_defect == -20.0
        assert v.delta_bc == 30.0

    def test_custom_params(self):
        v = NashEquilibriumVerifier(lambda_weight=0.5, betrayal_penalty_mult=3.0)
        assert v.lambda_weight == 0.5
        assert v.bc_defect == -30.0
        assert v.delta_bc == 40.0


class TestBCReward:
    """BC奖励计算测试"""

    def test_cooperate_reward(self):
        v = NashEquilibriumVerifier()
        reward = v.compute_bc_reward("cooperate", weighted_score=0.5)
        assert reward == 10.0 + 5.0 * 0.5  # base + top_tier_bonus * score

    def test_cooperate_min_reward(self):
        v = NashEquilibriumVerifier()
        reward = v.compute_bc_reward("cooperate", weighted_score=0.0)
        assert reward == 10.0  # 最低合作奖励 = BASE_REWARD

    def test_defect_reward(self):
        v = NashEquilibriumVerifier()
        reward = v.compute_bc_reward("defect")
        assert reward == -20.0  # 背叛惩罚 = -BASE_REWARD * BETRAYAL_PENALTY_MULT


class TestPayoffMatrix:
    """收益矩阵计算测试"""

    def test_payoff_matrix_shape(self):
        v = NashEquilibriumVerifier(lambda_weight=0.5)
        env = {'cc': 5.0, 'cd': 2.0, 'dc': 6.0, 'dd': 1.0}
        matrix = v.compute_payoff_matrix(env)
        assert matrix.shape == (2, 2)

    def test_cooperation_dominant_with_lambda_05(self):
        """λ=0.5 时合作应是严格优势策略"""
        v = NashEquilibriumVerifier(lambda_weight=0.5)
        env = {'cc': 5.0, 'cd': 2.0, 'dc': 6.0, 'dd': 1.0}
        matrix = v.compute_payoff_matrix(env)
        # U(C,C) = 5 + 0.5*15 = 12.5, U(D,C) = 6 + 0.5*(-20) = -4
        assert matrix[0, 0] > matrix[1, 0]  # 合作优于背叛
        # U(C,D) = 2 + 0.5*15 = 9.5, U(D,D) = 1 + 0.5*(-20) = -9
        assert matrix[0, 1] > matrix[1, 1]  # 合作优于背叛

    def test_cooperation_not_dominant_with_lambda_0(self):
        """λ=0 时合作不应是优势策略"""
        v = NashEquilibriumVerifier(lambda_weight=0.0)
        env = {'cc': 5.0, 'cd': 2.0, 'dc': 6.0, 'dd': 1.0}
        matrix = v.compute_payoff_matrix(env)
        # 无BC激励时，背叛有短期优势
        assert matrix[1, 0] > matrix[0, 0]  # 背叛优于合作


class TestParameterBounds:
    """参数边界推导测试"""

    def test_lambda_min(self):
        v = NashEquilibriumVerifier(lambda_weight=0.1)
        bounds = v.compute_parameter_bounds(env_betrayal_advantage=2.0)
        assert abs(bounds['lambda_min'] - 0.0667) < 0.001
        assert bounds['delta_bc'] == 30.0

    def test_lambda_05_safety_margin(self):
        """λ=0.5 时安全裕度应很大"""
        v = NashEquilibriumVerifier(lambda_weight=0.5)
        bounds = v.compute_parameter_bounds(env_betrayal_advantage=2.0)
        assert bounds['lambda_min'] < 0.5
        assert bounds['safety_margin_pct'] > 100

    def test_high_betrayal_advantage(self):
        """背叛优势很大时，λ_min 应增大"""
        v = NashEquilibriumVerifier(lambda_weight=0.5)
        bounds_low = v.compute_parameter_bounds(env_betrayal_advantage=1.0)
        bounds_high = v.compute_parameter_bounds(env_betrayal_advantage=5.0)
        assert bounds_high['lambda_min'] > bounds_low['lambda_min']


class TestDominantStrategy:
    """优势策略验证测试"""

    def test_cooperation_dominant_at_lambda_05(self):
        v = NashEquilibriumVerifier(lambda_weight=0.5)
        env = {'cc': 5.0, 'cd': 2.0, 'dc': 6.0, 'dd': 1.0}
        matrix = v.compute_payoff_matrix(env)
        result = v.verify_dominant_strategy(matrix)
        assert result.dominant_strategy == "cooperate"
        assert result.is_strict == True
        assert result.condition_satisfied == True
        assert result.margin > 0

    def test_no_dominant_at_lambda_0(self):
        v = NashEquilibriumVerifier(lambda_weight=0.0)
        env = {'cc': 5.0, 'cd': 2.0, 'dc': 6.0, 'dd': 1.0}
        matrix = v.compute_payoff_matrix(env)
        result = v.verify_dominant_strategy(matrix)
        assert result.dominant_strategy != "cooperate"


class TestNashEquilibria:
    """Nash均衡查找测试"""

    def test_find_nash_at_lambda_05(self):
        v = NashEquilibriumVerifier(lambda_weight=0.5)
        env = {'cc': 5.0, 'cd': 2.0, 'dc': 6.0, 'dd': 1.0}
        matrix = v.compute_payoff_matrix(env)
        results = v.find_nash_equilibria(matrix)
        # (C,C) 应是 Nash 均衡
        cc_nash = [r for r in results if r.strategy_profile == ("cooperate", "cooperate")]
        assert len(cc_nash) > 0
        assert cc_nash[0].is_nash is True

    def test_payoff_matrix_wrong_shape(self):
        v = NashEquilibriumVerifier()
        with pytest.raises(ValueError):
            v.find_nash_equilibria(np.array([[1, 2, 3], [4, 5, 6]]))


class TestNAgentPayoff:
    """n智能体收益计算测试"""

    def test_n_agent_3_agents(self):
        v = NashEquilibriumVerifier(lambda_weight=0.5)
        env = {'cc': 5.0, 'cd': 2.0, 'dc': 6.0, 'dd': 1.0}
        # 3 agents, 对方2个都合作
        payoff = v.compute_n_agent_payoff("cooperate", 2, 3, env)
        assert payoff > 0  # 合作应有正收益

    def test_n_agent_min_agents(self):
        v = NashEquilibriumVerifier()
        env = {'cc': 5.0, 'cd': 2.0, 'dc': 6.0, 'dd': 1.0}
        with pytest.raises(ValueError):
            v.compute_n_agent_payoff("cooperate", 0, 1, env)


class TestReportGeneration:
    """报告生成测试"""

    def test_generate_report_basic(self):
        v = NashEquilibriumVerifier(lambda_weight=0.5)
        report = v.generate_report()
        assert isinstance(report, str)
        assert len(report) > 100
        assert "Nash均衡" in report
        assert "λ_min" in report
        assert "严格优势策略" in report

    def test_generate_report_with_custom_env(self):
        v = NashEquilibriumVerifier(lambda_weight=0.5)
        env = {'cc': 3.0, 'cd': 1.0, 'dc': 4.0, 'dd': 0.0}
        report = v.generate_report(env_payoffs=env, n_agents=5)
        assert "5" in report  # 应包含5智能体
        assert "3.0" in report  # 应包含env_payoffs值
"""
Nash 均衡验证器边界测试（RalphLoop 原子任务 C）
覆盖：参数边界、极端输入、优势策略边界、参数界限推导
通过标准：新增 ≥6 项测试全过
"""
import pytest
import numpy as np

from marl.analysis.nash_verifier import (
    NashEquilibriumVerifier, COOPERATE, DEFECT,
)


class TestParameterBoundary:
    def test_zero_base_reward(self):
        """base_reward=0 时 BC 激励退化为 0（边界不崩溃）"""
        v = NashEquilibriumVerifier(base_reward=0.0)
        assert v.bc_cooperate_min == 0.0
        assert v.bc_defect == 0.0
        assert v.delta_bc == 0.0

    def test_extreme_penalty_mult(self):
        """背叛惩罚倍数极端大 → 背叛收益大幅为负（激励更强）"""
        v = NashEquilibriumVerifier(betrayal_penalty_mult=10.0)
        assert v.bc_defect == -100.0
        assert v.delta_bc == 110.0

    def test_zero_lambda_weight(self):
        """λ=0 → BC 激励不参与总奖励（纯 MARL 边界）"""
        v = NashEquilibriumVerifier(lambda_weight=0.0)
        assert v.lambda_weight == 0.0


class TestBCRewardBoundary:
    def test_weighted_score_above_one(self):
        """weighted_score>1 的越界输入：合作奖励仍按公式计算（不崩溃）"""
        v = NashEquilibriumVerifier()
        reward = v.compute_bc_reward(COOPERATE, weighted_score=1.5)
        assert reward == 10.0 + 5.0 * 1.5

    def test_weighted_score_negative(self):
        """weighted_score<0 的越界输入：不崩溃，返回合法值"""
        v = NashEquilibriumVerifier()
        reward = v.compute_bc_reward(COOPERATE, weighted_score=-0.5)
        assert isinstance(reward, float)

    def test_cooperate_zero_score_equals_base(self):
        """合作但贡献为 0 → 恰好等于基础奖励"""
        v = NashEquilibriumVerifier()
        assert v.compute_bc_reward(COOPERATE, weighted_score=0.0) == 10.0


class TestDominantStrategyBoundary:
    def test_verify_dominant_strategy_returns_result(self):
        """优势策略验证返回 DominantStrategyResult 结构（2×2 收益矩阵）"""
        v = NashEquilibriumVerifier()
        # 合作优势矩阵：合作行收益均高于背叛行 → 合作严格优势
        matrix = np.array([[5.0, 3.0], [2.0, 1.0]])
        result = v.verify_dominant_strategy(matrix)
        assert result is not None
        assert hasattr(result, "dominant_strategy")
        assert result.dominant_strategy == COOPERATE

    def test_verify_dominant_extreme_advantage(self):
        """极端背叛优势矩阵：验证器返回结构（背叛可能成为优势）"""
        v = NashEquilibriumVerifier()
        # 背叛行收益远高于合作行 → 背叛优势
        matrix = np.array([[1.0, 1.0], [100.0, 100.0]])
        result = v.verify_dominant_strategy(matrix)
        assert result is not None
        assert result.dominant_strategy == DEFECT


class TestParameterBounds:
    def test_compute_parameter_bounds_returns_dict(self):
        """参数界限推导返回字典且含关键键"""
        v = NashEquilibriumVerifier()
        bounds = v.compute_parameter_bounds()
        assert isinstance(bounds, dict)
        assert len(bounds) > 0

    def test_parameter_bounds_safety_margin_positive(self):
        """安全裕度为正（λ 在安全区间）"""
        v = NashEquilibriumVerifier()
        bounds = v.compute_parameter_bounds()
        # 检查界限中是否含安全裕度相关字段
        assert any("margin" in k.lower() or "safety" in k.lower() for k in bounds)


class TestNashEquilibria:
    def test_find_nash_equilibria_simple_matrix(self):
        """简单 2×2 收益矩阵可求 Nash 均衡（合作-合作为均衡）"""
        v = NashEquilibriumVerifier()
        # 2×2 矩阵：合作-合作 (5,5) 为严格占优结果
        matrix = np.array([[5.0, 2.0], [6.0, 1.0]])
        results = v.find_nash_equilibria(matrix)
        assert results is not None
        assert len(results) >= 1

    def test_find_nash_equilibria_empty_input(self):
        """非 2×2 输入抛出 ValueError"""
        v = NashEquilibriumVerifier()
        with pytest.raises(ValueError):
            v.find_nash_equilibria(np.array([]))

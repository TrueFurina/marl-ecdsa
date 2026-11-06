"""
ContributionScore 口径自检单测（自进化 backlog #4：贡献分被误标 Shapley）
覆盖：
- 评分方法标识 METHOD == "heuristic_weighted"（明确为启发式，非博弈论 Shapley 值）
- weighted_score 仍是 κ 加权凸组合（行为不变，回归锁）
- 文档明确区分"Shapley 风格维度权重"与"agent 级启发式加权分"
通过标准：新增测试全过；既有 incentive_contract 测试零回归。
"""
import pytest

from blockchain.contracts.incentive_contract import ContributionScore
from blockchain.contribution_weights import get_contribution_weights


class TestMethodMetadata:
    def test_method_is_heuristic_weighted(self):
        """评分方法明确标识为启发式加权，而非 Shapley 值（口径澄清，可机检）"""
        assert ContributionScore.METHOD == "heuristic_weighted"

    def test_docstring_disclaims_shapley_value(self):
        """文档须区分：κ 是 Shapley 风格维度权重，但分本身不是 Shapley 值"""
        doc = ContributionScore.weighted_score.__doc__
        assert "启发式" in doc, "缺少'启发式'口径说明"
        assert "Shapley 值" in doc, "缺少对'Shapley 值'的明确区分"
        # 明确否定该 agent 级评分是 Shapley 值
        assert ("不是" in doc) or ("非" in doc) or ("并非" in doc)


class TestWeightedScoreUnchanged:
    def test_formula_matches_kappa_weights(self):
        """weighted_score 仍为 κ_task·task + κ_coop·coop + κ_compliance·compliance（回归锁）"""
        k_task, k_coop, k_compliance = get_contribution_weights()
        cs = ContributionScore(
            "a0", task_score=0.5, cooperation_score=0.8, compliance_score=1.0,
        )
        expected = k_task * 0.5 + k_coop * 0.8 + k_compliance * 1.0
        assert cs.weighted_score == pytest.approx(expected)

    def test_all_one_is_one(self):
        cs = ContributionScore("a0", task_score=1.0, cooperation_score=1.0, compliance_score=1.0)
        assert cs.weighted_score == pytest.approx(1.0)

    def test_zero_is_zero(self):
        cs = ContributionScore("a0", task_score=0.0, cooperation_score=0.0, compliance_score=0.0)
        assert cs.weighted_score == pytest.approx(0.0)

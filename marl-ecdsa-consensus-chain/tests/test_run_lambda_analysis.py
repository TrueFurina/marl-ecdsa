"""
run_lambda_analysis 实验脚本测试（RalphLoop 原子任务 AH）
覆盖：extract_metrics 空/有数据、welch_ttest 数据不足/显著判断、报告生成
通过标准：新增 ≥6 项测试全过
"""
import json
import logging
from pathlib import Path

import numpy as np
import pytest

import run_lambda_analysis as rla

logging.basicConfig(level=logging.CRITICAL)


def _write_results(tmp_path, name, data):
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps(data), encoding='utf-8')
    return str(p)


class TestExtractMetrics:
    def test_empty_data_zeros(self, tmp_path):
        """空数据 → 所有指标回退 0.0"""
        path = _write_results(tmp_path, "empty", {})
        m = rla.extract_metrics(path)
        assert m["env_reward_last50"] == 0.0
        assert m["coop_rate_all"] == 0.0
        assert m["lambda_mean"] == 0.0
        assert m["convergence_episode"] == 0  # 空 → len=0

    def test_basic_metrics(self, tmp_path):
        """有数据 → 正确计算均值/最后50"""
        data = {"env_rewards": [1.0] * 100, "episode_rewards": [2.0] * 100,
                "cooperation_rates": [0.5] * 100, "lambda_history": [0.1, 0.2, 0.3]}
        path = _write_results(tmp_path, "basic", data)
        m = rla.extract_metrics(path)
        assert m["env_reward_last50"] == pytest.approx(1.0)
        assert m["coop_rate_all"] == pytest.approx(0.5)
        assert m["lambda_mean"] == pytest.approx(0.2)
        assert m["lambda_final"] == pytest.approx(0.3)
        assert m["lambda_max"] == pytest.approx(0.3)
        assert m["lambda_min"] == pytest.approx(0.1)

    def test_convergence_episode_detected(self, tmp_path):
        """收敛检测：早期达到最终性能 80% → 回合数较小"""
        env = [0.0] * 10 + [10.0] * 90  # 前10回合低，之后高
        data = {"env_rewards": env}
        path = _write_results(tmp_path, "conv", data)
        m = rla.extract_metrics(path)
        assert m["convergence_episode"] < 30  # 早期收敛


class TestWelchTTest:
    def test_insufficient_data(self):
        """样本不足 → insufficient_data"""
        r = rla.welch_ttest([1.0], [2.0, 3.0])
        assert r["test"] == "insufficient_data"

    def test_significant_difference(self):
        """显著差异：p < 0.05（welch_ttest 返回 np.True_，需真值判断）"""
        np.random.seed(42)
        a = np.random.normal(10.0, 0.5, 50)
        b = np.random.normal(5.0, 0.5, 50)
        r = rla.welch_ttest(a, b)
        assert bool(r["significant"]) is True
        assert float(r["p_value"]) < 0.05
        assert float(r["t_statistic"]) != 0

    def test_same_group_not_significant(self):
        """相同组 → 不显著"""
        a = np.random.normal(5.0, 0.1, 50)
        r = rla.welch_ttest(a, a)
        assert r["p_value"] > 0.05

    def test_improvement_pct(self):
        """improvement_pct 计算：均值差/基线绝对值"""
        a = np.array([12.0] * 20)
        b = np.array([10.0] * 20)
        r = rla.welch_ttest(a, b)
        assert r["improvement_pct"] == pytest.approx(20.0)  # (12-10)/10*100


class TestGenerateReport:
    def test_report_structure(self):
        """报告含敏感性/对比两部分（generate_report 期望 dict 输入）"""
        run = {'lambda_value': 0.1, 'env_reward_last50': 1.0, 'coop_rate_last50': 0.5,
               'lambda_mean': 0.1, 'lambda_std': 0.01}
        sensitivity = {"0.1": [run]}
        adaptive = {"adaptive": [run], "static": [run]}
        report = rla.generate_report(sensitivity, adaptive)
        assert isinstance(report, dict)
        assert "lambda_sensitivity" in report
        assert "adaptive_vs_static" in report  # 真实键名（非 adaptive_comparison）

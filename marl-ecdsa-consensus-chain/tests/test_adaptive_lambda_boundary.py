"""
自适应 λ 控制器边界测试（RalphLoop 原子任务 B）
覆盖：参数边界、极端输入、EMA 平滑、指标提取、重置
通过标准：新增 ≥6 项测试全过
"""
import pytest

from marl.integration.adaptive_lambda import AdaptiveLambdaController


class TestInitParams:
    def test_default_params(self):
        c = AdaptiveLambdaController()
        assert c.lambda_base == 0.1
        assert c._current_lambda == 0.1
        assert c.beta == 2.0
        assert c.threshold == 0.5
        assert c.ema_alpha == 0.9

    def test_custom_lambda_base(self):
        c = AdaptiveLambdaController(lambda_base=0.3)
        assert c._current_lambda == 0.3
        assert c._lambda_min == 0.3
        assert c._lambda_max == 0.3


class TestSigmoid:
    def test_sigmoid_zero(self):
        assert AdaptiveLambdaController._sigmoid(0.0) == pytest.approx(0.5)

    def test_sigmoid_positive_above_half(self):
        assert AdaptiveLambdaController._sigmoid(2.0) > 0.5

    def test_sigmoid_negative_below_half(self):
        assert AdaptiveLambdaController._sigmoid(-2.0) < 0.5

    def test_sigmoid_bounds(self):
        """sigmoid 值域严格在 (0,1)"""
        for x in [-10.0, -1.0, 0.0, 1.0, 10.0]:
            v = AdaptiveLambdaController._sigmoid(x)
            assert 0.0 < v < 1.0


class TestMetricExtraction:
    def test_extract_consensus_rate_default(self):
        c = AdaptiveLambdaController()
        # 空 stats → 默认率
        rate = c._extract_consensus_rate({})
        assert isinstance(rate, float)
        assert 0.0 <= rate <= 1.0

    def test_extract_coop_rate_default(self):
        c = AdaptiveLambdaController()
        rate = c._extract_coop_rate({})
        assert isinstance(rate, float)
        assert 0.0 <= rate <= 1.0

    def test_extract_security_rate_default(self):
        c = AdaptiveLambdaController()
        rate = c._extract_security_rate({})
        assert isinstance(rate, float)
        assert 0.0 <= rate <= 1.0


class TestComputeLambda:
    def test_compute_empty_stats_no_crash(self):
        """空统计字典不崩溃，返回有限 λ"""
        c = AdaptiveLambdaController()
        lam = c.compute_adaptive_lambda({})
        assert isinstance(lam, float)
        assert lam > 0

    def test_compute_updates_history(self):
        c = AdaptiveLambdaController()
        c.compute_adaptive_lambda({})
        assert len(c.get_adaptation_history()) == 1
        assert c._total_updates == 1

    def test_compute_high_metrics_raise_lambda(self):
        """高共识率/高合作率 → λ 提升（高于基准）"""
        c = AdaptiveLambdaController(lambda_base=0.1)
        stats = {
            'consensus_stats': {'consensus_success_rate': 0.9, 'rounds': 100},
            'cooperation_rate': 0.9,
            'security_stats': {'pass_count': 90, 'fail_count': 10},
        }
        lam = c.compute_adaptive_lambda(stats)
        assert lam > 0.1  # 高于基准

    def test_compute_ema_smoothing(self):
        """EMA 平滑：连续调用后变化平缓"""
        c = AdaptiveLambdaController(lambda_base=0.1)
        stats = {
            'consensus_stats': {'consensus_success_rate': 0.9, 'rounds': 100},
            'cooperation_rate': 0.9,
            'security_stats': {'pass_count': 90, 'fail_count': 10},
        }
        v1 = c.compute_adaptive_lambda(stats)
        v2 = c.compute_adaptive_lambda(stats)
        # EMA(alpha=0.9)：两次相同输入 → v2 接近 v1
        assert abs(v2 - v1) < 0.01


class TestStatsAndReset:
    def test_get_stats(self):
        c = AdaptiveLambdaController()
        c.compute_adaptive_lambda({})
        stats = c.get_stats()
        assert 'current_lambda' in stats or 'lambda' in stats
        assert 'total_updates' in stats

    def test_reset(self):
        c = AdaptiveLambdaController()
        c.compute_adaptive_lambda({})
        c.reset()
        assert c._current_lambda == c.lambda_base
        assert len(c.get_adaptation_history()) == 0
        assert c._total_updates == 0

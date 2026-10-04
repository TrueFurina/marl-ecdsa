"""
自适应λ控制器测试
覆盖：初始化、λ计算、统计信息、重置
"""
import pytest
import numpy as np
from marl.integration.adaptive_lambda import AdaptiveLambdaController


class TestAdaptiveLambdaInit:
    """初始化测试"""

    def test_default_params(self):
        ctrl = AdaptiveLambdaController()
        assert ctrl.lambda_base == 0.1
        assert ctrl.beta == 2.0
        assert ctrl.threshold == 0.5

    def test_custom_params(self):
        ctrl = AdaptiveLambdaController(lambda_base=0.5, beta=3.0)
        assert ctrl.lambda_base == 0.5
        assert ctrl.beta == 3.0


class TestComputeAdaptiveLambda:
    """λ计算测试"""

    def test_basic_computation(self):
        ctrl = AdaptiveLambdaController(lambda_base=0.5)
        stats = {'consensus_rate': 0.9, 'coop_rate': 0.8, 'security_rate': 1.0}
        lam = ctrl.compute_adaptive_lambda(stats)
        assert isinstance(lam, float)
        assert lam > 0

    def test_lambda_stays_in_range(self):
        """λ应在0.05~0.15范围内（默认配置）"""
        ctrl = AdaptiveLambdaController(lambda_base=0.1)
        stats = {'consensus_rate': 0.0, 'coop_rate': 0.0, 'security_rate': 0.0}
        lam = ctrl.compute_adaptive_lambda(stats)
        s = ctrl.get_stats()
        r = s['lambda_range']
        assert r[0] <= lam <= r[1]

    def test_high_performance_raises_lambda(self):
        """高性能指标应提高λ（相对于低性能）"""
        ctrl = AdaptiveLambdaController(lambda_base=0.1)
        low = ctrl.compute_adaptive_lambda({'consensus_rate': 0.1, 'coop_rate': 0.1, 'security_rate': 0.1})
        ctrl.reset()
        high = ctrl.compute_adaptive_lambda({'consensus_rate': 0.9, 'coop_rate': 0.9, 'security_rate': 1.0})
        assert high >= low


class TestGetStats:
    """统计信息测试"""

    def test_get_stats_after_computation(self):
        ctrl = AdaptiveLambdaController()
        ctrl.compute_adaptive_lambda({'consensus_rate': 0.8, 'coop_rate': 0.7, 'security_rate': 0.9})
        stats = ctrl.get_stats()
        assert 'current_lambda' in stats
        assert stats['total_updates'] == 1

    def test_get_adaptation_history(self):
        ctrl = AdaptiveLambdaController()
        ctrl.compute_adaptive_lambda({'consensus_rate': 0.8, 'coop_rate': 0.7, 'security_rate': 0.9})
        history = ctrl.get_adaptation_history()
        assert len(history) == 1
        assert 'lambda' in history[0]


class TestReset:
    """重置测试"""

    def test_reset_clears_history(self):
        ctrl = AdaptiveLambdaController()
        ctrl.compute_adaptive_lambda({'consensus_rate': 0.8, 'coop_rate': 0.7, 'security_rate': 0.9})
        ctrl.reset()
        assert len(ctrl.get_adaptation_history()) == 0
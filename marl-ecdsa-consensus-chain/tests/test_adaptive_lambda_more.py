"""
adaptive_lambda 更多边界测试（RalphLoop 原子任务 BR）
覆盖：指标提取各格式、驱动原因、统计结构、平滑收敛、重置
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from marl.integration.adaptive_lambda import AdaptiveLambdaController

logging.basicConfig(level=logging.CRITICAL)


class TestExtractMetrics:
    def test_consensus_rate_success_rate_field(self):
        """success_rate 字段格式"""
        c = AdaptiveLambdaController()
        stats = {'consensus_stats': {'success_rate': 0.8, 'rounds': 100}}
        assert c._extract_consensus_rate(stats) == pytest.approx(0.8)

    def test_consensus_rate_count_format(self):
        """success_count/total_rounds 格式"""
        c = AdaptiveLambdaController()
        stats = {'consensus_stats': {'success_count': 80, 'total_rounds': 100}}
        assert c._extract_consensus_rate(stats) == pytest.approx(0.8)

    def test_consensus_rate_zero_rounds_default(self):
        """total_rounds=0 → 默认率"""
        c = AdaptiveLambdaController()
        stats = {'consensus_stats': {'success_count': 0, 'total_rounds': 0}}
        rate = c._extract_consensus_rate(stats)
        assert 0.0 <= rate <= 1.0

    def test_security_rate_pct(self):
        """pass/fail 计算安全通过率"""
        c = AdaptiveLambdaController()
        stats = {'security_stats': {'pass_count': 90, 'fail_count': 10}}
        assert c._extract_security_rate(stats) == pytest.approx(0.9)


class TestDetermineReason:
    def test_reason_consensus_driven(self):
        """高综合值 + 高共识率 → 共识驱动（composite > threshold+0.1）"""
        c = AdaptiveLambdaController()
        reason = c._determine_reason(
            consensus_rate=0.9, coop_rate=0.3, security_rate=0.5, composite=0.7)
        assert "consensus" in reason  # dominant = consensus

    def test_reason_security_driven(self):
        """高综合值 + 最高安全率 → 安全驱动"""
        c = AdaptiveLambdaController()
        reason = c._determine_reason(
            consensus_rate=0.3, coop_rate=0.5, security_rate=0.9, composite=0.7)
        assert "security" in reason  # kappa_s*0.9 最高

    def test_reason_balanced(self):
        """中性综合值 → λ 稳定"""
        c = AdaptiveLambdaController()
        reason = c._determine_reason(
            consensus_rate=0.5, coop_rate=0.5, security_rate=0.5, composite=0.5)
        assert "stable" in reason  # 中性区间


class TestStatsAndConvergence:
    def test_get_stats_structure(self):
        c = AdaptiveLambdaController()
        c.compute_adaptive_lambda({})
        stats = c.get_stats()
        assert 'current_lambda' in stats
        assert 'total_updates' in stats

    def test_lambda_converges_same_input(self):
        """相同输入多次调用 → λ 平滑收敛（EMA）"""
        c = AdaptiveLambdaController(lambda_base=0.1)
        stats = {
            'consensus_stats': {'success_rate': 0.9, 'rounds': 100},
            'detector_stats': {'cooperation_rate': 0.8},
            'security_stats': {'pass_count': 90, 'fail_count': 10},
        }
        c.compute_adaptive_lambda(stats)  # 预热
        v1 = c.compute_adaptive_lambda(stats)
        v2 = c.compute_adaptive_lambda(stats)
        assert abs(v2 - v1) < 0.01  # EMA 收敛

    def test_reset_restores_base(self):
        c = AdaptiveLambdaController(lambda_base=0.1)
        c.compute_adaptive_lambda({})
        c.reset()
        assert c._current_lambda == 0.1
        assert len(c.get_adaptation_history()) == 0

    def test_history_records_reason(self):
        """历史记录含驱动原因"""
        c = AdaptiveLambdaController()
        c.compute_adaptive_lambda({})
        record = c.get_adaptation_history()[-1]
        assert 'lambda' in record
        assert 'reason' in record or 'bucket_index' in record

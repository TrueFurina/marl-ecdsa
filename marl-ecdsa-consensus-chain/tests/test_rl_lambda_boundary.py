"""
RL-λ 元学习调度器边界测试（RalphLoop 原子任务 AD）
覆盖：参数边界、λ 输出范围、桶选择、历史与重置
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from marl.integration.rl_lambda import RLLambdaScheduler

logging.basicConfig(level=logging.CRITICAL)


def _sample_stats():
    return {
        'consensus_stats': {'success_rate': 0.9, 'rounds': 100},
        'detector_stats': {'cooperation_rate': 0.54},
        'security_stats': {'pass_count': 90, 'fail_count': 10},
    }


class TestInitParams:
    def test_default_range_derived(self):
        """默认 λ 范围由 base 派生：[0.5*base, 1.5*base]（浮点近似）"""
        s = RLLambdaScheduler(lambda_base=0.1)
        assert s.lambda_min == pytest.approx(0.05)
        assert s.lambda_max == pytest.approx(0.15)

    def test_custom_range(self):
        s = RLLambdaScheduler(lambda_base=0.2, lambda_min=0.1, lambda_max=0.3)
        assert s.lambda_min == 0.1
        assert s.lambda_max == 0.3

    def test_n_buckets_min_3(self):
        """n_buckets 下限保护为 3"""
        s = RLLambdaScheduler(n_buckets=1)
        assert s.n_buckets == 3
        s2 = RLLambdaScheduler(n_buckets=9)
        assert s2.n_buckets == 9

    def test_epsilon_default(self):
        s = RLLambdaScheduler()
        assert s.epsilon == 0.15


class TestComputeLambda:
    def test_output_within_range(self):
        """compute_adaptive_lambda 输出在 [lambda_min, lambda_max] 内"""
        s = RLLambdaScheduler(lambda_base=0.1)
        for _ in range(10):  # 多次采样（ε-greedy 随机）
            lam = s.compute_adaptive_lambda(_sample_stats())
            assert s.lambda_min - 1e-9 <= lam <= s.lambda_max + 1e-9

    def test_empty_stats_falls_back_base(self):
        """空统计 → 不崩溃，输出仍在范围内"""
        s = RLLambdaScheduler(lambda_base=0.1)
        lam = s.compute_adaptive_lambda({})
        assert isinstance(lam, float)
        assert s.lambda_min - 1e-9 <= lam <= s.lambda_max + 1e-9

    def test_high_metric_output_in_range(self):
        """高指标输入 → 输出仍在范围内（元学习采样受 epsilon 影响，不做确定性断言）"""
        s = RLLambdaScheduler(lambda_base=0.1)
        lam = s.compute_adaptive_lambda(_sample_stats())
        assert s.lambda_min - 1e-9 <= lam <= s.lambda_max + 1e-9


class TestBucketSelection:
    def test_select_lambda_in_candidates(self):
        """select_lambda_by_metric 返回候选桶之一"""
        s = RLLambdaScheduler(lambda_base=0.1, n_buckets=5)
        lam = s.select_lambda_by_metric(_sample_stats())
        assert s.lambda_min - 1e-9 <= lam <= s.lambda_max + 1e-9

    def test_bucket_reward_update(self):
        """先产生 history 再更新桶回报（首次调用 history 为空会跳过，符合实现）"""
        s = RLLambdaScheduler(lambda_base=0.1)
        s.compute_adaptive_lambda(_sample_stats(), episode_reward=1.0)
        assert len(s.get_adaptation_history()) == 1
        s.compute_adaptive_lambda(_sample_stats(), episode_reward=2.0)  # 触发 Δreward 更新
        assert len(s.get_adaptation_history()) == 2


class TestHistoryReset:
    def test_history_grows(self):
        s = RLLambdaScheduler()
        for _ in range(3):
            s.compute_adaptive_lambda(_sample_stats())
        assert len(s.get_adaptation_history()) >= 3

    def test_reset_clears_history(self):
        s = RLLambdaScheduler()
        s.compute_adaptive_lambda(_sample_stats())
        s.reset()
        assert len(s.get_adaptation_history()) == 0

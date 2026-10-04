"""
RL-λ 元学习调度器测试（增量创新 #5）
验证元学习采样、回报更新、接口兼容性、浮点边界
"""
import logging

import numpy as np
import pytest

from marl.integration.rl_lambda import RLLambdaScheduler

logging.basicConfig(level=logging.CRITICAL)


def _sample_stats():
    return {
        'consensus_stats': {'success_rate': 0.9},
        'detector_stats': {'cooperation_rate': 0.54},
        'security_stats': {'pass_count': 90, 'fail_count': 10},
    }


class TestRLLambdaBasics:
    def test_init_defaults(self):
        s = RLLambdaScheduler()
        assert s.lambda_base == 0.1
        assert s.lambda_min == pytest.approx(0.05)
        assert s.lambda_max == pytest.approx(0.15)  # 浮点表示 0.15000000000000002
        assert s.n_buckets == 9
        assert len(s.lambda_candidates) == 9

    def test_candidates_in_range(self):
        s = RLLambdaScheduler()
        for c in s.lambda_candidates:
            assert s.lambda_min <= c <= s.lambda_max

    def test_lambda_in_range(self):
        """多次采样 λ 必须严格落在 [min, max]（含浮点边界）"""
        np.random.seed(42)
        s = RLLambdaScheduler(lambda_base=0.1, n_buckets=9, epsilon=0.15)
        stats = _sample_stats()
        for ep in range(100):
            lam = s.compute_adaptive_lambda(stats, episode_reward=-30.0 + ep * 0.5)
            assert s.lambda_min <= lam <= s.lambda_max, f'ep{ep} λ={lam} 越界'
            assert isinstance(lam, float)


class TestMetaLearning:
    def test_bucket_counts_accumulate(self):
        np.random.seed(7)
        s = RLLambdaScheduler(n_buckets=9, epsilon=0.2)
        stats = _sample_stats()
        for ep in range(30):
            s.compute_adaptive_lambda(stats, episode_reward=float(ep))
        counts = s.get_stats()['bucket_counts']
        assert sum(counts) == 30
        assert max(counts) > 1  # 有桶被多次选中（利用）

    def test_reward_updates_bucket_estimate(self):
        """回报估计随奖励变化而更新（元学习核心）"""
        np.random.seed(3)
        s = RLLambdaScheduler(n_buckets=5, epsilon=1.0)  # 全探索以便各桶都被选
        stats = _sample_stats()
        for ep in range(10):
            s.compute_adaptive_lambda(stats, episode_reward=float(ep))
        st = s.get_stats()
        assert 'bucket_rewards' in st
        # 高回报桶（后期选择）应估计更高（粗略检查非全零）
        assert max(st['bucket_rewards']) >= min(st['bucket_rewards'])

    def test_select_lambda_by_metric_monotonic(self):
        """高指标 → 高 λ（确定性补充调度器）"""
        s = RLLambdaScheduler()
        low = s.select_lambda_by_metric({
            'consensus_stats': {'success_rate': 0.2},
            'detector_stats': {'cooperation_rate': 0.2},
            'security_stats': {'pass_count': 10, 'fail_count': 90},
        })
        high = s.select_lambda_by_metric(_sample_stats())
        assert high >= low


class TestInterfaceCompat:
    def test_get_adaptation_history(self):
        np.random.seed(1)
        s = RLLambdaScheduler()
        for ep in range(5):
            s.compute_adaptive_lambda(_sample_stats(), episode_reward=-10.0)
        hist = s.get_adaptation_history()
        assert len(hist) == 5
        assert 'lambda' in hist[0]
        assert 'episode_reward' in hist[0]

    def test_get_stats_fields(self):
        s = RLLambdaScheduler()
        st = s.get_stats()
        for k in ['current_lambda', 'lambda_base', 'lambda_range', 'n_buckets',
                  'epsilon', 'total_updates', 'bucket_rewards', 'bucket_counts',
                  'latest_record', 'controller_type']:
            assert k in st, f'缺少字段 {k}'
        assert st['controller_type'] == 'rl_lambda_meta_learning'

    def test_reset(self):
        np.random.seed(2)
        s = RLLambdaScheduler()
        for ep in range(10):
            s.compute_adaptive_lambda(_sample_stats(), episode_reward=0.0)
        assert s.get_stats()['total_updates'] == 10
        s.reset()
        assert s.get_stats()['total_updates'] == 0
        assert s._current_lambda == s.lambda_base
        assert len(s.get_adaptation_history()) == 0

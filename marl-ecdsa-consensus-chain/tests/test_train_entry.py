"""
train.py 入口校验测试（RalphLoop 原子任务 AJ）
覆盖：TrainingConfig 默认值/覆盖、TrainingStats 记录/汇总
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from train import TrainingConfig, TrainingStats

logging.basicConfig(level=logging.CRITICAL)


class TestTrainingConfig:
    def test_defaults(self):
        cfg = TrainingConfig()
        assert cfg.n_agents == 3
        assert cfg.mode == 'bc_marl'
        assert cfg.seed == 42
        assert cfg.lambda_weight == 0.1
        assert cfg.algorithm == 'iql'
        assert cfg.adaptive_lambda is True
        assert cfg.verify_nash is True

    def test_kwargs_override(self):
        cfg = TrainingConfig(n_agents=5, mode='selfish', seed=7, lambda_weight=0.3)
        assert cfg.n_agents == 5
        assert cfg.mode == 'selfish'
        assert cfg.seed == 7
        assert cfg.lambda_weight == 0.3

    def test_ablation_flags_default_false(self):
        cfg = TrainingConfig()
        assert cfg.ablate_security is False
        assert cfg.ablate_consensus is False
        assert cfg.ablate_incentive is False

    def test_ablation_flags_enabled(self):
        cfg = TrainingConfig(ablate_security=True, ablate_consensus=True)
        assert cfg.ablate_security is True
        assert cfg.ablate_consensus is True
        assert cfg.ablate_incentive is False  # 未设置保持 False

    def test_consensus_shaping_default_off(self):
        """CARS 塑形默认关闭（需显式启用）"""
        cfg = TrainingConfig()
        assert cfg.consensus_shaping is False
        cfg2 = TrainingConfig(consensus_shaping=True, shaping_eta=0.1)
        assert cfg2.consensus_shaping is True
        assert cfg2.shaping_eta == 0.1


class TestTrainingStats:
    def test_record_episode_defaults(self):
        stats = TrainingStats()
        stats.record_episode(10.0, 25, {"a0": 5.0}, coop_rate=0.5)
        assert stats.episode_rewards == [10.0]
        assert stats.env_rewards == [10.0]  # 无 env_reward 时用 total
        assert stats.lambda_history == [0.1]  # 无 lambda 时默认 0.1

    def test_record_episode_explicit(self):
        stats = TrainingStats()
        stats.record_episode(10.0, 25, {"a0": 5.0}, 0.8, 0.1, env_reward=8.0, lambda_value=0.2)
        assert stats.env_rewards == [8.0]
        assert stats.lambda_history == [0.2]

    def test_record_loss_skips_none(self):
        stats = TrainingStats()
        stats.record_loss(None)
        stats.record_loss(0.5)
        assert stats.losses == [0.5]  # None 被跳过

    def test_summary_empty(self):
        stats = TrainingStats()
        summary = stats.summary()
        assert summary['total_episodes'] == 0
        assert summary['avg_reward'] == 0.0
        assert summary['avg_cooperation_rate'] == 0.0

    def test_summary_with_data(self):
        stats = TrainingStats()
        for i in range(10):
            stats.record_episode(float(i), 25, {"a0": 1.0}, coop_rate=0.5)
        summary = stats.summary(window=5)
        assert summary['total_episodes'] == 10
        assert summary['avg_reward'] == pytest.approx(4.5)
        assert summary['avg_cooperation_rate'] == pytest.approx(0.5)
        assert summary['avg_reward_last_5'] == pytest.approx(7.0)  # [5,6,7,8,9]

    def test_summary_window_larger_than_data(self):
        """window > 数据量 → 取全部"""
        stats = TrainingStats()
        stats.record_episode(1.0, 10, {}, coop_rate=1.0)
        summary = stats.summary(window=50)
        assert summary['avg_reward_last_50'] == pytest.approx(1.0)

"""
dashboard update_data 数据桥测试（RalphLoop 原子任务 BE）
覆盖：stats 更新、无 trainer 降级、异常捕获、子组件统计
通过标准：新增 ≥6 项测试全过
"""
import logging
from unittest.mock import MagicMock

import pytest

import visualization.dashboard as dash

logging.basicConfig(level=logging.CRITICAL)


class _FakeStats:
    def __init__(self):
        self.episode_rewards = [-30.0, -25.0]
        self.cooperation_rates = [0.5, 0.55]
        self.betrayal_rates = [0.0, 0.1]
        self.losses = [1.0, None, 2.0]  # 含 None 应被过滤
        self.bc_scores_history = [{"a0": 5.0}]
        self.avg_reward = -27.5

    def summary(self):
        return {"avg_reward": self.avg_reward}


def _fake_bridge():
    bridge = MagicMock()
    bridge.get_bc_scores.return_value = {"agent_0": 5.0}
    bridge._sign_count = 10
    bridge._verify_count = 8
    bridge.get_security_stats.return_value = {"total_alerts": 1}
    bridge.get_consensus_stats.return_value = {"rounds": 3}
    bridge.get_blockchain_stats.return_value = {"height": 3}
    bridge._signing.get_stats.return_value = {"ecdsa_sign_count": 10}
    bridge._recorder.get_stats.return_value = {"pending": 2}
    bridge._detector.get_stats.return_value = {"coop": 5}
    bridge._settlement.get_stats.return_value = {"lambda_weight": 0.1}
    return bridge


def _fake_trainer(bridge):
    trainer = MagicMock()
    trainer.bridge = bridge
    trainer.incentive_contract = MagicMock()
    trainer.incentive_contract.get_leaderboard.return_value = [("agent_0", 5.0)]
    return trainer


class TestStatsUpdate:
    def test_episode_rewards_copied(self):
        dash.update_data(_FakeStats())
        assert dash._dashboard_data['episode_rewards'] == [-30.0, -25.0]

    def test_losses_filter_none(self):
        """losses 中 None 被过滤"""
        dash.update_data(_FakeStats())
        assert dash._dashboard_data['losses'] == [1.0, 2.0]

    def test_summary_stored(self):
        dash.update_data(_FakeStats())
        assert dash._dashboard_data['summary'] == {"avg_reward": -27.5}


class TestNoTrainerFallback:
    def test_without_trainer_zeros(self):
        """无 trainer → 区块链相关字段回退空值"""
        dash.update_data(_FakeStats())
        assert dash._dashboard_data['bc_scores'] == {}
        assert dash._dashboard_data['leaderboard'] == []
        assert dash._dashboard_data['ecdsa_stats'] == {}
        assert dash._dashboard_data['blockchain_stats'] == {}


class TestWithTrainer:
    def test_bridge_data_populated(self):
        """有 trainer + bridge → 区块链数据填充"""
        bridge = _fake_bridge()
        trainer = _fake_trainer(bridge)
        dash.update_data(_FakeStats(), trainer)
        assert dash._dashboard_data['bc_scores'] == {"agent_0": 5.0}
        assert dash._dashboard_data['leaderboard'] == [{"agent_id": "agent_0", "score": 5.0}]
        assert dash._dashboard_data['ecdsa_stats'] == {'sign_count': 10, 'verify_count': 8}

    def test_subcomponent_stats(self):
        """子组件独立统计填充"""
        bridge = _fake_bridge()
        trainer = _fake_trainer(bridge)
        dash.update_data(_FakeStats(), trainer)
        assert dash._dashboard_data['signing_stats']['ecdsa_sign_count'] == 10
        assert dash._dashboard_data['detector_stats']['coop'] == 5


class TestExceptionFallback:
    def test_leaderboard_exception_fallback(self):
        """排行榜加载异常 → 回退空列表（不崩溃）"""
        bridge = _fake_bridge()
        trainer = _fake_trainer(bridge)
        trainer.incentive_contract.get_leaderboard.side_effect = RuntimeError("boom")
        dash.update_data(_FakeStats(), trainer)
        assert dash._dashboard_data['leaderboard'] == []

    def test_bridge_stats_exception_fallback(self):
        """桥接统计异常 → 回退空字典（不崩溃）"""
        bridge = _fake_bridge()
        bridge.get_security_stats.side_effect = RuntimeError("boom")
        trainer = _fake_trainer(bridge)
        dash.update_data(_FakeStats(), trainer)
        assert dash._dashboard_data['security_stats'] == {}
        assert dash._dashboard_data['blockchain_stats'] == {}

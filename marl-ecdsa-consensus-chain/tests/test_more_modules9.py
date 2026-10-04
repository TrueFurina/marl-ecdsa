"""
更多模块剩余边界测试（RalphLoop 原子任务 DL）
覆盖：cw_pbft 权重更新边界、权重历史、阈值检查（此前未单点覆盖）
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from blockchain.consensus.cw_pbft import CWPBFTConsensus, ConsensusVote

logging.basicConfig(level=logging.CRITICAL)

NODES = ['node_0', 'node_1', 'node_2']


@pytest.fixture
def pbft():
    return CWPBFTConsensus('node_0', NODES)


class TestWeightUpdate:
    def test_update_weight_normal(self, pbft):
        """正常权重更新"""
        pbft.update_weight('node_1', 0.8)
        assert pbft.get_weights()['node_1'] == 0.8

    def test_update_weight_min_protected(self, pbft):
        """低于 MIN_WEIGHT 被下界保护"""
        pbft.update_weight('node_1', 0.01)
        assert pbft.get_weights()['node_1'] == pbft.MIN_WEIGHT == 0.1

    def test_update_weight_zero_ban(self, pbft):
        """封禁节点权重置 0"""
        pbft.update_weight('node_1', 0.0)
        assert pbft.get_weights()['node_1'] == 0.0

    def test_update_weight_unregistered_ignored(self, pbft):
        """未注册节点更新忽略"""
        before = dict(pbft.get_weights())
        pbft.update_weight('ghost', 0.9)
        assert pbft.get_weights() == before


class TestWeightHistory:
    def test_history_records_updates(self, pbft):
        """权重历史记录更新"""
        pbft.update_weight('node_1', 0.8)
        pbft.update_weight('node_2', 0.5)
        history = pbft.get_weight_history()
        assert len(history) == 2
        assert history[-1]['weights']['node_2'] == 0.5

    def test_total_weight_updated(self, pbft):
        """总权重随更新同步"""
        pbft.update_weight('node_1', 2.0)
        assert pbft._total_weight == pytest.approx(sum(pbft.get_weights().values()))

    def test_history_empty_initial(self, pbft):
        """初始历史为空"""
        assert pbft.get_weight_history() == []


class TestWeightThreshold:
    def test_threshold_no_votes_false(self, pbft):
        """无投票 → 未达阈值"""
        assert pbft._check_weight_threshold('prepare') is False

    def test_threshold_all_votes_true(self, pbft):
        """全节点投票 → 达阈值（2/3）"""
        pbft.start_consensus('hash_t')
        for nid in NODES:
            pbft._votes['prepare'][nid] = ConsensusVote(
                voter_id=nid, block_hash='hash_t', phase='prepare',
                weight=pbft._weights[nid])
        assert pbft._check_weight_threshold('prepare') is True

    def test_threshold_partial_false(self, pbft):
        """部分投票 → 未达阈值"""
        pbft.start_consensus('hash_p')
        pbft._votes['prepare']['node_0'] = ConsensusVote(
            voter_id='node_0', block_hash='hash_p', phase='prepare',
            weight=pbft._weights['node_0'])
        assert pbft._check_weight_threshold('prepare') is False


class TestWeightsSnapshot:
    def test_get_weights_returns_copy(self, pbft):
        """get_weights 返回副本（修改不影响内部）"""
        weights = pbft.get_weights()
        weights['node_1'] = 99.0
        assert pbft.get_weights()['node_1'] != 99.0

    def test_all_nodes_initial_weight(self, pbft):
        """初始全节点有权重（>0）"""
        weights = pbft.get_weights()
        assert set(weights.keys()) == set(NODES)
        assert all(w > 0 for w in weights.values())

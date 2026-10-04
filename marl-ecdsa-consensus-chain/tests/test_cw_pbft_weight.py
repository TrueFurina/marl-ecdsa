"""
CW-PBFT 权重更新边界测试（RalphLoop 原子任务 R）
覆盖：update_weight 下界保护、封禁置零、权重历史、阈值检查
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


class TestUpdateWeight:
    def test_update_weight_normal(self, pbft):
        pbft.update_weight('node_1', 0.8)
        assert pbft.get_weights()['node_1'] == 0.8

    def test_update_weight_below_min_protected(self, pbft):
        """非封禁节点权重受 MIN_WEIGHT(0.1) 下界保护（P1-8）"""
        pbft.update_weight('node_1', 0.02)  # 低于下界
        assert pbft.get_weights()['node_1'] == pbft.MIN_WEIGHT == 0.1

    def test_update_weight_banned_node_zero(self, pbft):
        """封禁节点（new_weight<=0）权重置 0（失去投票权）"""
        pbft.update_weight('node_1', 0.0)
        assert pbft.get_weights()['node_1'] == 0.0

    def test_update_weight_unregistered_ignored(self, pbft):
        """未注册节点不更新（无副作用）"""
        before = dict(pbft.get_weights())
        pbft.update_weight('ghost_node', 0.9)
        assert pbft.get_weights() == before


class TestWeightHistory:
    def test_weight_history_recorded(self, pbft):
        pbft.update_weight('node_1', 0.8)
        pbft.update_weight('node_2', 0.5)
        history = pbft.get_weight_history()
        assert len(history) == 2
        assert history[-1]['weights']['node_2'] == 0.5

    def test_total_weight_updated(self, pbft):
        pbft.update_weight('node_1', 0.8)
        assert pbft._total_weight == pytest.approx(sum(pbft.get_weights().values()))


class TestWeightThreshold:
    def test_threshold_not_reached_initially(self, pbft):
        assert pbft._check_weight_threshold('prepare') is False  # 无投票

    def test_threshold_reached_with_enough_weight(self, pbft):
        pbft.start_consensus('hash_thr')
        # 全部节点投票 prepare（权重和 = 总权重 → 达到 2/3）
        for nid in NODES:
            pbft._votes['prepare'][nid] = ConsensusVote(
                voter_id=nid, block_hash='hash_thr', phase='prepare',
                weight=pbft._weights[nid],
            )
        assert pbft._check_weight_threshold('prepare') is True

    def test_threshold_not_reached_with_partial_weight(self, pbft):
        pbft.start_consensus('hash_part')
        # 仅一个节点投票（权重 < 2/3 总权重）
        pbft._votes['prepare']['node_0'] = ConsensusVote(
            voter_id='node_0', block_hash='hash_part', phase='prepare',
            weight=pbft._weights['node_0'],
        )
        assert pbft._check_weight_threshold('prepare') is False


class TestWeightedVoting:
    def test_high_weight_dominates(self, pbft):
        """高贡献节点权重大 → 少数高权重节点可达到阈值"""
        pbft.update_weight('node_1', 2.0)
        pbft.update_weight('node_2', 0.1)
        total = sum(pbft.get_weights().values())
        pbft.start_consensus('hash_dom')
        # node_1(2.0) + node_0(初始) 投票
        pbft._votes['prepare']['node_1'] = ConsensusVote(
            voter_id='node_1', block_hash='hash_dom', phase='prepare', weight=2.0)
        pbft._votes['prepare']['node_0'] = ConsensusVote(
            voter_id='node_0', block_hash='hash_dom', phase='prepare',
            weight=pbft._weights['node_0'])
        voted = sum(v.weight for v in pbft._votes['prepare'].values())
        assert voted >= (2 / 3) * total

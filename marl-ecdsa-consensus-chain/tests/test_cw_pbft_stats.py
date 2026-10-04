"""
CW-PBFT consensus_stats 边界测试（RalphLoop 原子任务 U）
覆盖：统计结构、成功率、投票计数、权重演化、初始化状态
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from blockchain.consensus.cw_pbft import CWPBFTConsensus

logging.basicConfig(level=logging.CRITICAL)

NODES = ['node_0', 'node_1', 'node_2']


@pytest.fixture
def pbft():
    return CWPBFTConsensus('node_0', NODES)


class TestInitialStats:
    def test_stats_structure(self, pbft):
        stats = pbft.get_consensus_stats()
        for key in ['node_id', 'state', 'n_nodes', 'f_tolerance', 'weights',
                    'consensus_success_rate', 'weight_derivation']:
            assert key in stats

    def test_initial_success_rate_zero(self, pbft):
        stats = pbft.get_consensus_stats()
        assert stats['consensus_success_rate'] == 0.0  # 无轮次 → 0

    def test_initial_votes_empty(self, pbft):
        stats = pbft.get_consensus_stats()
        assert stats['prepare_votes'] == 0
        assert stats['commit_votes'] == 0

    def test_initial_state_idle(self, pbft):
        stats = pbft.get_consensus_stats()
        assert stats['state'].name == 'IDLE'  # ConsensusState.IDLE


class TestStatsAfterConsensus:
    def test_stats_after_fast_consensus_success(self, pbft):
        pbft.fast_consensus('hash_fc', 'node_0')
        stats = pbft.get_consensus_stats()
        assert stats['consensus_success_rate'] == 1.0
        assert pbft.consensus_success_count == 1

    def test_stats_after_simulated_success(self, pbft):
        pbft.simulated_consensus('hash_sim', 'node_0')
        stats = pbft.get_consensus_stats()
        assert stats['consensus_success_rate'] == 1.0
        assert stats['current_block_hash'] == 'hash_sim'

    def test_stats_after_fail_round(self, pbft):
        """模拟失败轮次：成功率为 0"""
        pbft.consensus_fail_count = 1
        stats = pbft.get_consensus_stats()
        assert stats['consensus_success_rate'] == 0.0


class TestWeightDerivation:
    def test_weight_derivation_keys(self, pbft):
        stats = pbft.get_consensus_stats()
        wd = stats['weight_derivation']
        assert wd['κ_task'] == 0.40
        assert wd['κ_coop'] == 0.35
        assert wd['κ_compliance'] == 0.25

    def test_weights_present(self, pbft):
        stats = pbft.get_consensus_stats()
        assert set(stats['weights'].keys()) == set(NODES)


class TestFaultTolerance:
    def test_f_tolerance_3_nodes(self, pbft):
        stats = pbft.get_consensus_stats()
        assert stats['f_tolerance'] == 0  # floor((3-1)/3) = 0

    def test_f_tolerance_4_nodes(self):
        pbft4 = CWPBFTConsensus('node_0', ['node_0', 'node_1', 'node_2', 'node_3'])
        stats = pbft4.get_consensus_stats()
        assert stats['f_tolerance'] == 1  # floor((4-1)/3) = 1

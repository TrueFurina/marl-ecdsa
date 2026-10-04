"""
标准 PBFT 共识引擎测试（等权基线）
验证与 CW-PBFT 的接口兼容性与三阶段流程
"""
import logging

import pytest

from blockchain.consensus.cw_pbft import ConsensusState, ConsensusVote
from blockchain.consensus.standard_pbft import StandardPBFTConsensus

logging.basicConfig(level=logging.CRITICAL)

NODES_3 = ['node_0', 'node_1', 'node_2']
NODES_4 = ['node_0', 'node_1', 'node_2', 'node_3']


class TestStandardPBFTInit:
    def test_equal_weights(self):
        pbft = StandardPBFTConsensus('node_0', NODES_4)
        assert pbft.get_weights() == {n: 1.0 for n in NODES_4}
        assert pbft.n == 4
        assert pbft.f == 1  # floor((4-1)/3)

    def test_primary_rotation(self):
        pbft = StandardPBFTConsensus('node_0', NODES_3)
        assert pbft.get_primary(0) == 'node_0'
        assert pbft.get_primary(10) == 'node_1'  # BLOCKS_PER_ROTATION=10


class TestConsensusFlow:
    def test_start_consensus(self):
        pbft = StandardPBFTConsensus('node_0', NODES_3)
        vote = pbft.start_consensus('hash_001')
        assert pbft.get_state() == ConsensusState.PRE_PREPARE
        assert vote.phase == 'pre_prepare'
        assert vote.weight == 1.0

    def test_prepare_threshold(self):
        """3节点：阈值 ceil(2*3/3)=2"""
        pbft = StandardPBFTConsensus('node_0', NODES_3)
        pbft.receive_pre_prepare('hash_001', 'node_0')
        v1 = ConsensusVote('node_1', 'hash_001', 'prepare', 1.0)
        commit = pbft.receive_vote(v1)
        # 第1票未达阈值(2)，不返回commit
        assert commit is None
        v2 = ConsensusVote('node_2', 'hash_001', 'prepare', 1.0)
        commit2 = pbft.receive_vote(v2)
        assert commit2 is not None
        assert commit2.phase == 'commit'

    def test_full_flow_reaches_committed(self):
        pbft = StandardPBFTConsensus('node_0', NODES_3)
        # 主节点发起提案 → 副本节点需先 receive_pre_prepare 进入 PREPARE 态
        pbft.start_consensus('hash_002')
        pbft.receive_pre_prepare('hash_002', 'node_0')
        pbft.receive_vote(ConsensusVote('node_1', 'hash_002', 'prepare', 1.0))
        pbft.receive_vote(ConsensusVote('node_2', 'hash_002', 'prepare', 1.0))
        pbft.receive_vote(ConsensusVote('node_1', 'hash_002', 'commit', 1.0))
        pbft.receive_vote(ConsensusVote('node_2', 'hash_002', 'commit', 1.0))
        assert pbft.is_consensus_reached() is True

    def test_reset(self):
        pbft = StandardPBFTConsensus('node_0', NODES_3)
        pbft.start_consensus('hash_003')
        pbft.reset()
        assert pbft.get_state() == ConsensusState.IDLE
        assert pbft._current_block_hash is None

    def test_weight_compat_methods(self):
        """network_consensus 兼容方法"""
        pbft = StandardPBFTConsensus('node_0', NODES_3)
        pbft.update_weight('node_1', 0.5)  # 等权模式忽略
        assert pbft.get_weights()['node_1'] == 1.0
        # _check_weight_threshold 别名可用
        assert callable(pbft._check_weight_threshold)

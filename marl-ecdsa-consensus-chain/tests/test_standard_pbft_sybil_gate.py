"""等权 PBFT 基线女巫门控回归锁（2026-11-03）

缺陷形态：`StandardPBFTConsensus.receive_vote` 没有校验投票者是否在共识成员
集合内，而阈值按 `len(self._votes[phase])`（投票者**个数**）计数。于是任何
调用方塞进任意伪造的 voter_id，就能凭空凑够 `ceil(2n/3)`。

已实测：n=4（阈值 3）时，单个节点在**零个真实对等节点**参与的情况下，用
`ghost_1/ghost_2/ghost_3` 三个捏造身份即可跑完 PREPARE→COMMIT 并宣布共识
达成 —— 同一组伪造投票在 CW-PBFT 下被全部拒收。

CW-PBFT 在 09-28（全检 #2）就加了「非共识成员身份一律拒收」，等权基线漏了
同一个门控。而等权基线正是对比实验的对照组（`factory` 用
`mode='standard_pbft'` 创建），其共识安全属性不应弱于被对照的对象。

本文件锁住四件事：
1. 非成员投票被拒收，不入库；
2. 仅凭伪造身份无法达成共识（含端到端三阶段）；
3. 真实成员投票照常达成共识（不误杀）；
4. 两个引擎对同一组伪造投票的行为一致（接口语义对齐）。
"""
import logging

from blockchain.consensus.cw_pbft import ConsensusState, ConsensusVote
from blockchain.consensus.standard_pbft import StandardPBFTConsensus

logging.basicConfig(level=logging.CRITICAL)

NODES_4 = ['node_0', 'node_1', 'node_2', 'node_3']   # n=4, f=1, 阈值 ceil(8/3)=3
GHOSTS = ['ghost_1', 'ghost_2', 'ghost_3']


def _prepared(node_id='node_0', block_hash='blk'):
    """构造一个已进入 PREPARE 状态的等权引擎。"""
    pbft = StandardPBFTConsensus(node_id, NODES_4)
    pbft.receive_pre_prepare(block_hash, node_id)
    return pbft


class TestSybilGate:
    def test_non_member_vote_rejected(self):
        """非成员投票被拒收：不入库"""
        pbft = _prepared()
        assert pbft.receive_vote(
            ConsensusVote('ghost_1', 'blk', 'prepare', 1.0)
        ) is None
        assert 'ghost_1' not in pbft._votes['prepare']

    def test_non_member_cannot_trigger_prepare_threshold(self):
        """伪造身份凑不出 PREPARE 阈值（不会返回 COMMIT 票）"""
        pbft = _prepared()
        for g in GHOSTS:
            assert pbft.receive_vote(
                ConsensusVote(g, 'blk', 'prepare', 1.0)
            ) is None
        assert pbft.get_state() == ConsensusState.PREPARE
        assert pbft._votes['prepare'] == {}

    def test_phantom_quorum_cannot_reach_consensus(self):
        """端到端：零个真实对等节点 + 三个伪造身份 → 不得达成共识"""
        pbft = _prepared()
        for g in GHOSTS:
            pbft.receive_vote(ConsensusVote(g, 'blk', 'prepare', 1.0))
        for g in GHOSTS:
            pbft.receive_vote(ConsensusVote(g, 'blk', 'commit', 1.0))
        assert pbft.is_consensus_reached() is False
        assert pbft.consensus_success_count == 0

    def test_self_reported_weight_normalized(self):
        """自报 weight 不是第二个可信通道：入库值恒为权威值 1.0"""
        pbft = _prepared()
        pbft.receive_vote(ConsensusVote('node_1', 'blk', 'prepare', 999.0))
        assert pbft._votes['prepare']['node_1'].weight == 1.0

    def test_caller_object_not_mutated(self):
        """权重纠偏存副本，不就地改写入参"""
        pbft = _prepared()
        vote = ConsensusVote('node_1', 'blk', 'prepare', 999.0)
        pbft.receive_vote(vote)
        assert vote.weight == 999.0


class TestGenuineQuorumStillWorks:
    def test_real_votes_reach_consensus(self):
        """真实成员投票照常达成共识（防止修复误杀）"""
        pbft = _prepared()
        # n=4 → 阈值 3，需要三个真实成员投票
        rets = [pbft.receive_vote(ConsensusVote(nid, 'blk', 'prepare', 1.0))
                for nid in ('node_1', 'node_2', 'node_3')]
        assert rets[0] is None and rets[1] is None
        assert rets[2] is not None and rets[2].phase == 'commit'

        for nid in ('node_1', 'node_2', 'node_3'):
            pbft.receive_vote(ConsensusVote(nid, 'blk', 'commit', 1.0))
        assert pbft.is_consensus_reached() is True
        assert pbft.consensus_success_count == 1

    def test_mixed_real_and_ghost_counts_only_real(self):
        """真伪混投：只统计真实成员，伪造身份不帮忙凑票"""
        pbft = _prepared()
        pbft.receive_vote(ConsensusVote('node_1', 'blk', 'prepare', 1.0))
        for g in GHOSTS:
            pbft.receive_vote(ConsensusVote(g, 'blk', 'prepare', 1.0))
        # 只有 node_1 一票 < 阈值 3
        assert pbft.get_state() == ConsensusState.PREPARE
        assert set(pbft._votes['prepare']) == {'node_1'}


class TestParityWithCWPBFT:
    def test_both_engines_reject_same_ghost_votes(self):
        """两个引擎对同一组伪造投票的行为必须一致（接口语义对齐）"""
        from blockchain.consensus.cw_pbft import CWPBFTConsensus

        std = _prepared()
        cw = CWPBFTConsensus('node_0', NODES_4)
        cw.receive_pre_prepare('blk', 'node_0')

        for g in GHOSTS:
            std_ret = std.receive_vote(ConsensusVote(g, 'blk', 'prepare', 1.0))
            cw_ret = cw.receive_vote(ConsensusVote(g, 'blk', 'prepare', 1.0))
            assert std_ret is None and cw_ret is None

        assert std._votes['prepare'] == {}
        assert cw._votes['prepare'] == {}

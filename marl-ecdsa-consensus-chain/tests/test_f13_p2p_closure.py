# -*- coding: utf-8 -*-
"""F13 负测（2026-11-02 赛后）：TCP 科研分支 PBFT 封闭性。

钉住四道新门（engineering_findings F13）：
  C1 —— PRE-PREPARE 主节点合法性：声称者必须 == get_primary(block_height)
  C2 —— 类型混淆：PREPARE 票签名重放为 COMMIT 必须被 phase 校验拒绝
  C3 —— COMMIT 前提：本节点未达成 prepared 时，他人 COMMIT 票不得计入
  C4 —— 轮次绑定：签名体含 block_height，跨轮消息直接丢弃
以及三节点全握手正向路径（修复不得把正常流程打死）。
"""
import asyncio
import json

import pytest

from blockchain.network.message_protocol import MessageProtocol, MessageType
from blockchain.consensus.cw_pbft import ConsensusState as _CS
from blockchain.network.network_consensus import NetworkConsensusNode

NODES = ['node_0', 'node_1', 'node_2']
PORT = 7950


def _mk_node(node_id):
    """不启动网络的节点（insecure 投票模式，隔离协议层逻辑）。
    broadcast 换成捕获器；权重均一，保证阈值语义确定性。"""
    node = NetworkConsensusNode(
        node_id=node_id, host='127.0.0.1', port=PORT,
        all_node_ids=NODES, allow_insecure_vote=True, enable_tls=False,
        consensus_mode='cw_pbft',
    )
    node.cw_pbft._weights = {n: 1.0 for n in NODES}
    calls = []

    async def _fake_broadcast(msg_type, data, signature=None):
        calls.append((msg_type, dict(data), signature))

    node.p2p.broadcast = _fake_broadcast
    return node, calls


def _msg(msg_type, data, from_node, nonce=1):
    return MessageProtocol.build(msg_type, from_node=from_node, data=data, nonce=nonce)


def _body(voter, height, phase, bh='blk_hash_f13'):
    return {'voter_id': voter, 'block_hash': bh, 'phase': phase,
            'weight': 1.0, 'timestamp': 0, 'block_height': height}


class TestF13Closure:
    def test_c1_non_primary_preprepare_dropped(self):
        """高度 11 的合法主节点是 node_1（(11//10)%3=1）——node_0 冒充必须被拒。"""
        node, calls = _mk_node('node_1')
        asyncio.run(node._on_preprepare(
            _msg(MessageType.CONSENSUS_PREPREPARE,
                 _body('node_0', 11, 'pre_prepare'), 'node_0'), 'node_0'))
        assert calls == []
        assert node.cw_pbft._current_block_hash is None
        assert node._round_height is None

    def test_c1_valid_primary_accepted(self):
        node, calls = _mk_node('node_1')
        asyncio.run(node._on_preprepare(
            _msg(MessageType.CONSENSUS_PREPREPARE,
                 _body('node_0', 1, 'pre_prepare'), 'node_0'), 'node_0'))
        assert len(calls) == 1  # 自己的 PREPARE 广播
        assert node._round_height == 1
        assert node.cw_pbft._current_block_hash == 'blk_hash_f13'

    def test_c2_phase_confusion_dropped(self):
        """PREPARE 票（phase='prepare'）喂给 COMMIT handler 必须被拒。"""
        node, _ = _mk_node('node_1')
        asyncio.run(node._on_preprepare(
            _msg(MessageType.CONSENSUS_PREPREPARE,
                 _body('node_0', 1, 'pre_prepare'), 'node_0'), 'node_0'))
        commits_before = dict(node.cw_pbft._votes['commit'])
        asyncio.run(node._on_commit(
            _msg(MessageType.CONSENSUS_COMMIT,
                 _body('node_0', 1, 'prepare'), 'node_0'), 'node_0'))
        assert node.cw_pbft._votes['commit'] == commits_before
        assert node.cw_pbft._state != _CS.COMMITTED

    def test_c3_commit_without_prepared_dropped(self):
        """副本刚收到 PRE-PREPARE（未达 prepare 阈值）时，他人 COMMIT 票不得计入。"""
        node, _ = _mk_node('node_2')
        asyncio.run(node._on_preprepare(
            _msg(MessageType.CONSENSUS_PREPREPARE,
                 _body('node_0', 1, 'pre_prepare'), 'node_0'), 'node_0'))
        assert node.cw_pbft._state == _CS.PREPARE
        asyncio.run(node._on_commit(
            _msg(MessageType.CONSENSUS_COMMIT,
                 _body('node_0', 1, 'commit'), 'node_0'), 'node_0'))
        assert node.cw_pbft._state == _CS.PREPARE
        assert node.cw_pbft._votes['commit'] == {}

    def test_c4_wrong_round_dropped(self):
        node, calls = _mk_node('node_1')
        asyncio.run(node._on_preprepare(
            _msg(MessageType.CONSENSUS_PREPREPARE,
                 _body('node_0', 1, 'pre_prepare'), 'node_0'), 'node_0'))
        n_calls = len(calls)
        asyncio.run(node._on_prepare(
            _msg(MessageType.CONSENSUS_PREPARE,
                 _body('node_2', 2, 'prepare'), 'node_2'), 'node_2'))
        assert len(calls) == n_calls  # 高度 2 ≠ 本轮 1 → 无 COMMIT 广播

    def test_happy_path_three_nodes_converge(self):
        """修复后三节点全握手：PRE-PREPARE → PREPARE×3 → COMMIT×3 → 全员 COMMITTED。"""
        nodes = {n: _mk_node(n)[0] for n in NODES}
        primary, height, bh = 'node_0', 1, 'blk_hash_f13'
        for n in NODES:
            nodes[n]._round_height = height
        nodes[primary].cw_pbft.start_consensus(bh)

        async def deliver(src, msg_type, data):
            for nid in NODES:
                if nid == src:
                    continue
                h = getattr(nodes[nid], '_on_' + msg_type.value)
                await h(_msg(msg_type, data, src), src)

        async def flow():
            await deliver(primary, MessageType.CONSENSUS_PREPREPARE,
                          _body(primary, height, 'pre_prepare', bh))
            # 收集各副本 prepare 广播并投递（主节点自己的 prepare 票已在池内）
            for _ in range(3):
                for src in NODES:
                    for mt, data, _sig in list(nodes[src].p2p.broadcast_buffer):
                        if mt == MessageType.CONSENSUS_PREPARE:
                            await deliver(src, mt, data)
                    nodes[src].p2p.broadcast_buffer.clear()
            # 收集 commit 广播并投递
            for _ in range(3):
                for src in NODES:
                    for mt, data, _sig in list(nodes[src].p2p.broadcast_buffer):
                        if mt == MessageType.CONSENSUS_COMMIT:
                            await deliver(src, mt, data)
                    nodes[src].p2p.broadcast_buffer.clear()

        for n in NODES:
            nodes[n].p2p.broadcast_buffer = []
            # 捕获器改写为带缓冲的版本
            node = nodes[n]
            node.p2p.broadcast_buffer = []

            async def _capturing(msg_type, data, signature=None, _n=n):
                nodes[_n].p2p.broadcast_buffer.append((msg_type, dict(data), signature))

            node.p2p.broadcast = _capturing

        asyncio.run(flow())
        from blockchain.consensus.cw_pbft import ConsensusState as _CS
        assert all(nodes[n].cw_pbft._state == _CS.COMMITTED for n in NODES)

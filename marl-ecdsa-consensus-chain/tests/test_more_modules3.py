"""
更多模块剩余边界测试（RalphLoop 原子任务 CZ）
覆盖：message_protocol 编解码/字段提取、network_consensus 权重委托
通过标准：新增 ≥6 项测试全过
"""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blockchain.network.message_protocol import MessageProtocol, MessageType
from blockchain.network.network_consensus import NetworkConsensusNode

logging.basicConfig(level=logging.CRITICAL)

NODES = ['node_0', 'node_1', 'node_2']


class TestMessageProtocol:
    def test_build_structure(self):
        """build 构造消息含 header/body.data（真实结构：data 在 body 内）"""
        msg = MessageProtocol.build(MessageType.HEARTBEAT, "node_0",
                                    data={"ts": 1}, nonce=1)
        assert 'header' in msg
        assert 'body' in msg
        assert msg['header']['msg_type'] == MessageType.HEARTBEAT
        assert msg['body']['data'] == {"ts": 1}

    def test_encode_decode_roundtrip(self):
        """encode→decode 往返一致"""
        msg = MessageProtocol.build(MessageType.CONSENSUS_PREPARE, "node_1",
                                    data={"hash": "abc"}, nonce=5)
        encoded = MessageProtocol.encode(msg)
        decoded = MessageProtocol.decode(encoded)
        assert decoded == msg

    def test_encode_4byte_length_prefix(self):
        """编码含 4 字节长度前缀"""
        msg = MessageProtocol.build(MessageType.HEARTBEAT, "node_0", data={}, nonce=1)
        encoded = MessageProtocol.encode(msg)
        prefix_len = int.from_bytes(encoded[:4], 'big')
        assert prefix_len == len(encoded[4:])


class TestMessageFields:
    def test_get_msg_id_deterministic(self):
        """消息 ID 确定（同消息一致）"""
        msg = MessageProtocol.build(MessageType.HEARTBEAT, "node_0", data={}, nonce=1)
        assert MessageProtocol.get_msg_id(msg) == MessageProtocol.get_msg_id(msg)

    def test_get_msg_type(self):
        msg = MessageProtocol.build(MessageType.HEARTBEAT, "node_0", data={}, nonce=1)
        assert MessageProtocol.get_msg_type(msg) == MessageType.HEARTBEAT

    def test_get_from_node(self):
        msg = MessageProtocol.build(MessageType.HEARTBEAT, "node_2", data={}, nonce=1)
        assert MessageProtocol.get_from_node(msg) == "node_2"

    def test_get_data(self):
        msg = MessageProtocol.build(MessageType.BLOCK, "node_0",
                                    data={"block_hash": "abc"}, nonce=1)
        assert MessageProtocol.get_data(msg) == {"block_hash": "abc"}

    def test_get_signature_none_default(self):
        """无签名消息 → get_signature 返回 None"""
        msg = MessageProtocol.build(MessageType.HEARTBEAT, "node_0", data={}, nonce=1)
        assert MessageProtocol.get_signature(msg) is None


class TestNetworkWeight:
    def test_update_weight_delegates(self):
        """NetworkConsensusNode update_weight 委托 CW-PBFT"""
        node = NetworkConsensusNode(node_id='node_0', host='127.0.0.1', port=7601,
                                    all_node_ids=NODES)
        node.update_weight('node_1', 0.8)
        assert node.get_weights()['node_1'] == 0.8

    def test_weights_min_protected(self):
        """权重下界保护（非封禁节点）"""
        node = NetworkConsensusNode(node_id='node_0', host='127.0.0.1', port=7602,
                                    all_node_ids=NODES)
        node.update_weight('node_1', 0.01)
        assert node.get_weights()['node_1'] >= 0.1  # MIN_WEIGHT

    def test_get_stats_structure(self):
        """get_stats 含关键字段"""
        node = NetworkConsensusNode(node_id='node_0', host='127.0.0.1', port=7603,
                                    all_node_ids=NODES)
        stats = node.get_stats()
        for key in ['node_id', 'port', 'msg_sent', 'msg_received',
                    'consensus_rounds', 'network', 'weights']:
            assert key in stats

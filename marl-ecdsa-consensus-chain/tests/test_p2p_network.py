"""
P2P 网络共识模块测试
覆盖：消息协议编解码、节点信息、消息去重、共识节点初始化
"""
import pytest
import json
import time
from blockchain.network.message_protocol import MessageProtocol, MessageType
from blockchain.network.p2p_node import NodeInfo, P2PNode
from blockchain.network.network_consensus import NetworkConsensusNode


class TestMessageProtocol:
    """消息协议编解码测试"""

    def test_build_message(self):
        msg = MessageProtocol.build(MessageType.HEARTBEAT, "node_0", {"status": "ok"}, nonce=1)
        assert msg["header"]["msg_type"] == MessageType.HEARTBEAT
        assert msg["header"]["from_node"] == "node_0"
        assert msg["header"]["nonce"] == 1
        assert "msg_id" in msg["header"]

    def test_encode_decode_roundtrip(self):
        original = MessageProtocol.build(MessageType.TRANSACTION, "agent_0",
                                         {"action": 3, "position": [0.5, 0.3]}, nonce=42)
        encoded = MessageProtocol.encode(original)
        assert len(encoded) > 4
        length = int.from_bytes(encoded[:4], 'big')
        assert length == len(encoded) - 4
        decoded = json.loads(encoded[4:].decode('utf-8'))
        assert decoded["header"]["msg_type"] == original["header"]["msg_type"].value
        assert decoded["header"]["from_node"] == "agent_0"

    def test_msg_id_unique_per_nonce(self):
        m1 = MessageProtocol.build(MessageType.HEARTBEAT, "n0", {}, nonce=1)
        m2 = MessageProtocol.build(MessageType.HEARTBEAT, "n0", {}, nonce=2)
        assert MessageProtocol.get_msg_id(m1) != MessageProtocol.get_msg_id(m2)

    def test_msg_id_format(self):
        """测试 msg_id 格式（16位hex）"""
        m1 = MessageProtocol.build(MessageType.HEARTBEAT, "n0", {}, nonce=1)
        msg_id = MessageProtocol.get_msg_id(m1)
        assert len(msg_id) == 16
        assert all(c in '0123456789abcdef' for c in msg_id)

    def test_all_message_types(self):
        for mt in [MessageType.HEARTBEAT, MessageType.REGISTER, MessageType.TRANSACTION,
                    MessageType.BLOCK, MessageType.SYNC_REQUEST, MessageType.SYNC_RESPONSE,
                    MessageType.CONSENSUS_PREPREPARE, MessageType.CONSENSUS_PREPARE,
                    MessageType.CONSENSUS_COMMIT]:
            msg = MessageProtocol.build(mt, "test", {"data": 1}, nonce=1)
            assert msg["header"]["msg_type"] == mt

    def test_large_payload(self):
        large_data = {"values": list(range(1000))}
        msg = MessageProtocol.build(MessageType.BLOCK, "node_0", large_data, nonce=1)
        encoded = MessageProtocol.encode(msg)
        assert len(encoded) > 100
        decoded = json.loads(encoded[4:].decode('utf-8'))
        assert len(decoded["body"]["data"]["values"]) == 1000

    def test_signature_field(self):
        msg = MessageProtocol.build(MessageType.REGISTER, "node_0", {"key": "val"}, nonce=1, signature="abc123")
        assert msg["body"]["signature"] == "abc123"

    def test_timestamp_auto_generated(self):
        msg = MessageProtocol.build(MessageType.HEARTBEAT, "n0", {}, nonce=1)
        assert "timestamp" in msg["header"]
        assert abs(msg["header"]["timestamp"] - int(time.time() * 1000)) < 5000

    def test_msg_id_length(self):
        msg = MessageProtocol.build(MessageType.HEARTBEAT, "n0", {}, nonce=1)
        msg_id = MessageProtocol.get_msg_id(msg)
        assert len(msg_id) == 16


class TestCWPBFTMessages:
    """CW-PBFT 共识消息测试"""

    def test_preprepare_message(self):
        msg = MessageProtocol.build(MessageType.CONSENSUS_PREPREPARE, "primary_0",
                                     {"block_hash": "a1b2c3d4", "view": 1}, nonce=1)
        assert msg["header"]["msg_type"] == MessageType.CONSENSUS_PREPREPARE
        assert msg["body"]["data"]["block_hash"] == "a1b2c3d4"

    def test_prepare_message(self):
        msg = MessageProtocol.build(MessageType.CONSENSUS_PREPARE, "replica_1",
                                     {"block_hash": "a1b2c3d4", "weight": 1.5}, nonce=1)
        assert msg["body"]["data"]["weight"] == 1.5

    def test_commit_message(self):
        msg = MessageProtocol.build(MessageType.CONSENSUS_COMMIT, "replica_2",
                                     {"block_hash": "a1b2c3d4", "signature": "sig_hex"}, nonce=1)
        assert msg["body"]["data"]["signature"] == "sig_hex"

    def test_consensus_msg_chain(self):
        """模拟三阶段共识消息链"""
        block_hash = "abc123def456"
        primary = "node_0"
        replica_1 = "node_1"
        replica_2 = "node_2"

        pp = MessageProtocol.build(MessageType.CONSENSUS_PREPREPARE, primary,
                                    {"block_hash": block_hash, "view": 1}, nonce=1)
        assert pp["header"]["from_node"] == primary

        pr = MessageProtocol.build(MessageType.CONSENSUS_PREPARE, replica_1,
                                    {"block_hash": block_hash, "weight": 1.0}, nonce=1)
        assert pr["body"]["data"]["weight"] == 1.0

        cm = MessageProtocol.build(MessageType.CONSENSUS_COMMIT, replica_2,
                                    {"block_hash": block_hash, "signature": "sig"}, nonce=1)
        assert cm["body"]["data"]["block_hash"] == block_hash


class TestNodeInfo:
    """节点信息测试"""

    def test_node_info_creation(self):
        node = NodeInfo("agent_0", "127.0.0.1", 7001)
        assert node.node_id == "agent_0"
        assert node.host == "127.0.0.1"
        assert node.port == 7001
        assert node.is_online is True
        assert node.last_heartbeat > 0

    def test_node_info_repr(self):
        node = NodeInfo("agent_0", "127.0.0.1", 7001)
        assert "agent_0" in repr(node)
        assert "7001" in repr(node)

    def test_node_info_offline(self):
        node = NodeInfo("agent_0", "127.0.0.1", 7001)
        node.is_online = False
        assert node.is_online is False


class TestP2PNodeInit:
    """P2P 节点初始化测试"""

    def test_p2p_node_creation(self):
        node = P2PNode("node_0", "127.0.0.1", 7001, is_consensus_node=True)
        assert node.node_id == "node_0"
        assert node.host == "127.0.0.1"
        assert node.port == 7001
        assert node.is_consensus_node is True
        assert len(node._peers) == 0
        assert len(node._connections) == 0

    def test_p2p_node_lightweight(self):
        node = P2PNode("agent_0", "127.0.0.1", 7002, is_consensus_node=False)
        assert node.is_consensus_node is False

    def test_p2p_node_constants(self):
        assert P2PNode.HEARTBEAT_INTERVAL == 5
        assert P2PNode.NODE_TIMEOUT == 30
        assert P2PNode.MAX_MSG_CACHE == 10000

    def test_p2p_node_initial_nonce(self):
        node = P2PNode("node_0", "127.0.0.1", 7001)
        assert node._nonce == 0

    def test_p2p_node_register_handler(self):
        node = P2PNode("node_0", "127.0.0.1", 7001)
        async def dummy_handler(msg, from_node): pass
        node.register_handler("custom_type", dummy_handler)
        assert "custom_type" in node._handlers
        assert node._handlers["custom_type"] == dummy_handler

    def test_p2p_node_default_handlers(self):
        node = P2PNode("node_0", "127.0.0.1", 7001)
        for mt in [MessageType.HEARTBEAT, MessageType.REGISTER]:
            assert mt.value in node._handlers


class TestNetworkConsensusInit:
    """网络共识节点初始化测试"""

    def test_network_consensus_creation(self):
        node = NetworkConsensusNode("node_0", "127.0.0.1", 7001,
                                    all_node_ids=["node_0", "node_1", "node_2"])
        assert node.node_id == "node_0"
        assert node.host == "127.0.0.1"
        assert node.port == 7001
        assert node.all_node_ids == ["node_0", "node_1", "node_2"]
        assert node.msg_sent == 0
        assert node.msg_received == 0
        assert node.consensus_rounds == 0

    def test_network_consensus_p2p_created(self):
        node = NetworkConsensusNode("node_0", "127.0.0.1", 7001,
                                    all_node_ids=["node_0", "node_1", "node_2"])
        assert node.p2p is not None
        assert node.p2p.node_id == "node_0"
        assert node.p2p.port == 7001

    def test_network_consensus_cw_pbft_created(self):
        node = NetworkConsensusNode("node_0", "127.0.0.1", 7001,
                                    all_node_ids=["node_0", "node_1", "node_2"])
        assert node.cw_pbft is not None
        assert node.cw_pbft.node_id == "node_0"
        assert node.cw_pbft.consensus_nodes == ["node_0", "node_1", "node_2"]

    def test_network_consensus_handlers_registered(self):
        node = NetworkConsensusNode("node_0", "127.0.0.1", 7001,
                                    all_node_ids=["node_0", "node_1", "node_2"])
        for mt in [MessageType.CONSENSUS_PREPREPARE, MessageType.CONSENSUS_PREPARE,
                    MessageType.CONSENSUS_COMMIT]:
            assert mt.value in node.p2p._handlers
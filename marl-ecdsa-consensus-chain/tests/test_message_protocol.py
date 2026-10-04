"""
消息协议测试
覆盖 MessageProtocol 构建/编码/解码/字段提取
（P2P 网络消息协议，MARL-ECDSA 共识链）
"""
import json

import pytest

from blockchain.network.message_protocol import MessageProtocol, MessageType


class TestMessageBuild:
    def test_build_structure(self):
        msg = MessageProtocol.build(
            MessageType.TRANSACTION, "agent_0", {"action": [0.1, 0.2]}, nonce=1,
        )
        assert "header" in msg and "body" in msg
        assert msg["header"]["msg_type"] == "transaction"
        assert msg["header"]["from_node"] == "agent_0"
        assert msg["header"]["nonce"] == 1
        assert msg["body"]["data"] == {"action": [0.1, 0.2]}
        assert msg["body"]["signature"] is None

    def test_msg_id_deterministic_for_same_content(self):
        """同内容（含 nonce/时间戳相同才确定）——此处验证 msg_id 是内容哈希前16位"""
        msg1 = MessageProtocol.build(MessageType.HEARTBEAT, "node_0", {}, nonce=5)
        msg2 = MessageProtocol.build(MessageType.HEARTBEAT, "node_0", {}, nonce=5)
        # 同秒内时间戳相同 → msg_id 应相同
        if msg1["header"]["timestamp"] == msg2["header"]["timestamp"]:
            assert msg1["header"]["msg_id"] == msg2["header"]["msg_id"]
        assert len(msg1["header"]["msg_id"]) == 16

    def test_signature_preserved(self):
        msg = MessageProtocol.build(
            MessageType.CONSENSUS_PREPARE, "node_1", {"block_hash": "abc"}, nonce=2,
            signature="0xdeadbeef",
        )
        assert msg["body"]["signature"] == "0xdeadbeef"


class TestMessageCodec:
    def test_encode_decode_roundtrip(self):
        original = MessageProtocol.build(
            MessageType.BLOCK, "node_2", {"height": 10, "hash": "h10"}, nonce=3,
            signature="sig_10",
        )
        raw = MessageProtocol.encode(original)
        # 4字节长度前缀 + payload
        decoded = MessageProtocol.decode(raw)
        assert decoded == original

    def test_decode_too_short_raises(self):
        with pytest.raises(ValueError):
            MessageProtocol.decode(b"\x00\x00")  # < 4 字节

    def test_encode_has_length_prefix(self):
        msg = MessageProtocol.build(MessageType.QUERY, "node_0", {"q": 1}, nonce=0)
        raw = MessageProtocol.encode(msg)
        length = int.from_bytes(raw[:4], "big")
        assert length == len(raw) - 4
        assert length > 0

    def test_decode_chinese_content(self):
        """中文内容 ensure_ascii=False 编码往返"""
        msg = MessageProtocol.build(MessageType.RESPONSE, "node_0", {"msg": "共识完成"}, nonce=1)
        raw = MessageProtocol.encode(msg)
        decoded = MessageProtocol.decode(raw)
        assert decoded["body"]["data"]["msg"] == "共识完成"


class TestMessageFieldExtraction:
    def test_getters(self):
        msg = MessageProtocol.build(
            MessageType.CONSENSUS_COMMIT, "node_3", {"block_hash": "abc"}, nonce=7,
            signature="sig7",
        )
        assert MessageProtocol.get_msg_id(msg) == msg["header"]["msg_id"]
        assert MessageProtocol.get_msg_type(msg) == "commit"
        assert MessageProtocol.get_from_node(msg) == "node_3"
        assert MessageProtocol.get_data(msg) == {"block_hash": "abc"}
        assert MessageProtocol.get_signature(msg) == "sig7"

    def test_getters_missing_fields(self):
        empty = {}
        assert MessageProtocol.get_msg_id(empty) == ""
        assert MessageProtocol.get_msg_type(empty) == ""
        assert MessageProtocol.get_from_node(empty) == ""
        assert MessageProtocol.get_data(empty) is None
        assert MessageProtocol.get_signature(empty) is None


class TestMessageTypeEnum:
    def test_enum_values(self):
        assert MessageType.REGISTER.value == "register"
        assert MessageType.CONSENSUS_PREPREPARE.value == "preprepare"
        assert MessageType.CONSENSUS_PREPARE.value == "prepare"
        assert MessageType.CONSENSUS_COMMIT.value == "commit"
        assert MessageType.TRANSACTION.value == "transaction"
        assert MessageType.HEARTBEAT.value == "heartbeat"
        assert MessageType.BLOCK.value == "block"
        assert MessageType.SYNC_REQUEST.value == "sync_request"
        assert MessageType.SYNC_RESPONSE.value == "sync_response"
        assert MessageType.QUERY.value == "query"
        assert MessageType.RESPONSE.value == "response"

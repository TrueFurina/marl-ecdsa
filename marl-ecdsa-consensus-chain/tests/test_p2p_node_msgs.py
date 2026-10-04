"""
p2p_node 消息/连接管理测试（RalphLoop 原子任务 AX）
覆盖：在线节点过滤、send_to 连接状态、broadcast 去重/排除、handler 注册
通过标准：新增 ≥6 项测试全过
"""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from blockchain.network.p2p_node import NodeInfo, P2PNode
from blockchain.network.message_protocol import MessageType

logging.basicConfig(level=logging.CRITICAL)


@pytest.fixture
def node():
    return P2PNode("node_0", "127.0.0.1", 7701)


class TestPeerQueries:
    def test_get_online_peers_filters_offline(self, node):
        node._peers["node_1"] = NodeInfo("node_1", "127.0.0.1", 7702)   # online
        node._peers["node_2"] = NodeInfo("node_2", "127.0.0.1", 7703)
        node._peers["node_2"].is_online = False                          # offline
        online = node.get_online_peers()
        ids = [p.node_id for p in online]
        assert "node_1" in ids
        assert "node_2" not in ids

    def test_get_consensus_peers_matches_online(self, node):
        node._peers["node_1"] = NodeInfo("node_1", "127.0.0.1", 7702)
        node._peers["node_2"] = NodeInfo("node_2", "127.0.0.1", 7703)
        node._peers["node_2"].is_online = False
        assert len(node.get_consensus_peers()) == len(node.get_online_peers()) == 1

    def test_no_peers_empty(self, node):
        assert node.get_online_peers() == []


class TestSendTo:
    def test_send_to_unconnected_returns_false(self, node):
        """未连接节点 → 返回 False"""
        assert asyncio.run(node.send_to("ghost", MessageType.HEARTBEAT, {})) is False

    def test_send_to_connected_returns_true(self, node):
        """已连接节点 → writer 写入成功返回 True（mock writer）"""
        writer = MagicMock()
        writer.write = MagicMock()
        writer.drain = AsyncMock()
        node._connections["node_1"] = (MagicMock(), writer)
        result = asyncio.run(node.send_to("node_1", MessageType.HEARTBEAT, {"ts": 1}))
        assert result is True
        writer.write.assert_called_once()


class TestBroadcast:
    def test_broadcast_no_peers_no_crash(self, node):
        """无连接 → 广播不崩溃"""
        asyncio.run(node.broadcast(MessageType.HEARTBEAT, {}))

    def test_broadcast_exclude_skips(self, node):
        """广播排除指定节点"""
        writer1 = MagicMock(); writer1.write = MagicMock(); writer1.drain = AsyncMock()
        writer2 = MagicMock(); writer2.write = MagicMock(); writer2.drain = AsyncMock()
        node._connections["node_1"] = (MagicMock(), writer1)
        node._connections["node_2"] = (MagicMock(), writer2)
        asyncio.run(node.broadcast(MessageType.HEARTBEAT, {}, exclude="node_1"))
        assert writer2.write.called  # node_2 收到
        assert not writer1.write.called  # node_1 被排除

    def test_broadcast_dedup_records_msg_id(self, node):
        """广播后 msg_id 被记录到去重集（防转发环；每次 nonce 递增故 msg_id 不同）"""
        writer = MagicMock(); writer.write = MagicMock(); writer.drain = AsyncMock()
        node._connections["node_1"] = (MagicMock(), writer)
        asyncio.run(node.broadcast(MessageType.BLOCK, {"h": 1}))
        assert len(node._seen_msg_ids) == 1  # 消息已记录去重
        # 再次广播 → nonce 递增生成新 msg_id → 继续发送（新消息）
        asyncio.run(node.broadcast(MessageType.BLOCK, {"h": 1}))
        assert len(node._seen_msg_ids) == 2


class TestHandlerRegistration:
    def test_register_handler_stores(self, node):
        calls = []

        async def fake(msg, from_node):
            calls.append(msg)

        node.register_handler(MessageType.QUERY, fake)
        assert MessageType.QUERY in node._handlers

    def test_default_handlers_registered(self, node):
        """REGISTER/HEARTBEAT 默认处理器已注册"""
        assert MessageType.REGISTER in node._handlers
        assert MessageType.HEARTBEAT in node._handlers

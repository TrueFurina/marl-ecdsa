"""
P2P 节点核心逻辑测试
覆盖 NodeInfo、P2PNode 初始化、离线标记、消息缓存修剪等同步方法
（P2P 网络层，MARL-ECDSA 共识链）
"""
import time

import pytest

from blockchain.network.p2p_node import NodeInfo, P2PNode
from blockchain.network.message_protocol import MessageType


class TestNodeInfo:
    def test_creation(self):
        info = NodeInfo("node_1", "127.0.0.1", 7002)
        assert info.node_id == "node_1"
        assert info.host == "127.0.0.1"
        assert info.port == 7002
        assert info.is_online is True

    def test_repr(self):
        info = NodeInfo("node_1", "127.0.0.1", 7002)
        assert "node_1" in repr(info)

    def test_mark_offline(self):
        info = NodeInfo("node_1", "127.0.0.1", 7002)
        info.is_online = False
        assert info.is_online is False


class TestP2PNodeInit:
    def test_node_creation(self):
        node = P2PNode("node_0", "127.0.0.1", 7001, is_consensus_node=True)
        assert node.node_id == "node_0"
        assert node.port == 7001
        assert node.is_consensus_node is True

    def test_default_handlers_registered(self):
        node = P2PNode("node_0", "127.0.0.1", 7001)
        # REGISTER/HEARTBEAT 默认处理器应已注册
        assert MessageType.REGISTER in node._handlers
        assert MessageType.HEARTBEAT in node._handlers


class TestP2PMsgCache:
    def test_trim_msg_cache(self):
        node = P2PNode("node_0", "127.0.0.1", 7001)
        # _seen_msg_ids 是 set（去重缓存），_msg_order 是 FIFO 顺序 dict
        # trim 时按 _msg_order 删除最旧一半，需同时模拟两个结构
        for i in range(node.MAX_MSG_CACHE + 50):
            mid = f"msg_{i}"
            node._seen_msg_ids.add(mid)
            node._msg_order[mid] = i
        assert len(node._seen_msg_ids) > node.MAX_MSG_CACHE
        node._trim_msg_cache()
        # 删除最旧一半（MAX_MSG_CACHE//2）→ 剩余 = (MAX_MSG_CACHE+50) - MAX_MSG_CACHE//2
        remaining = len(node._seen_msg_ids)
        assert remaining == (node.MAX_MSG_CACHE + 50) - node.MAX_MSG_CACHE // 2
        assert remaining <= node.MAX_MSG_CACHE


class TestP2POnlinePeers:
    def test_get_online_peers_filters_offline(self):
        node = P2PNode("node_0", "127.0.0.1", 7001)
        node._peers["node_1"] = NodeInfo("node_1", "127.0.0.1", 7002)   # online
        node._peers["node_2"] = NodeInfo("node_2", "127.0.0.1", 7003)
        node._peers["node_2"].is_online = False                          # offline
        online = node.get_online_peers()
        online_ids = [p.node_id for p in online]
        assert "node_1" in online_ids
        assert "node_2" not in online_ids

    def test_mark_offline(self):
        node = P2PNode("node_0", "127.0.0.1", 7001)
        node._peers["node_1"] = NodeInfo("node_1", "127.0.0.1", 7002)
        node._mark_offline("node_1")
        assert node._peers["node_1"].is_online is False

    def test_register_handler(self):
        node = P2PNode("node_0", "127.0.0.1", 7001)
        calls = []

        async def fake_handler(msg, from_node):
            calls.append((msg, from_node))

        node.register_handler(MessageType.QUERY, fake_handler)
        assert MessageType.QUERY in node._handlers

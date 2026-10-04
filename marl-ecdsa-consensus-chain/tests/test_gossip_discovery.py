"""
Gossip 动态节点发现测试
覆盖初始化、动态入网（notify_join）、离线感知（cleanup）、启动/停止
（阶段二：Gossip 动态入网/离线感知增强，MARL-ECDSA 共识链）
"""
import time

import pytest

from blockchain.network.gossip_discovery import GossipDiscovery, PeerInfo


class TestGossipInit:
    def test_initial_views_empty(self):
        g = GossipDiscovery("node_0")
        assert g.node_id == "node_0"
        assert g.active_view == {}
        assert g.passive_view == {}
        assert g.get_active_peers() == []
        assert g.get_peer_count() == 0

    def test_config_defaults(self):
        g = GossipDiscovery("node_0")
        assert g.k_view == 5
        assert g.max_peers == 20
        assert g.base_port == 7001
        assert g.DEAD_TIMEOUT > 0


class TestGossipJoin:
    def test_notify_join_adds_active(self):
        g = GossipDiscovery("node_0", k_view=5)
        g.notify_join("node_1", "127.0.0.1", 7002)
        assert "node_1" in g.active_view
        assert g.get_peer_count() == 1
        peers = g.get_active_peers()
        assert peers[0].node_id == "node_1"
        assert peers[0].port == 7002

    def test_notify_join_self_ignored(self):
        g = GossipDiscovery("node_0")
        g.notify_join("node_0", "127.0.0.1", 7001)
        assert g.get_peer_count() == 0

    def test_notify_join_over_capacity_goes_passive(self):
        g = GossipDiscovery("node_0", k_view=2)
        for i in range(1, 6):
            g.notify_join(f"node_{i}", "127.0.0.1", 7000 + i)
        # k_view=2 → 前2个在 active，其余在 passive
        assert len(g.active_view) == 2
        assert len(g.passive_view) == 3
        assert g.get_peer_count() == 5


class TestGossipCleanup:
    def test_cleanup_dead_peers_moves_to_passive(self):
        g = GossipDiscovery("node_0", k_view=5)
        g.notify_join("node_1", "127.0.0.1", 7002)
        # 人为把 last_seen 推到超时之前
        g.active_view["node_1"].last_seen = time.time() - g.DEAD_TIMEOUT - 10
        g._cleanup_dead_peers()
        assert "node_1" not in g.active_view
        assert "node_1" in g.passive_view
        assert g.passive_view["node_1"].is_active is False
        assert g.get_active_peers() == []

    def test_cleanup_fresh_peer_untouched(self):
        g = GossipDiscovery("node_0", k_view=5)
        g.notify_join("node_1", "127.0.0.1", 7002)
        g._cleanup_dead_peers()
        assert "node_1" in g.active_view

    def test_cleanup_removes_dead_passive(self):
        g = GossipDiscovery("node_0", k_view=2)
        for i in range(1, 5):
            g.notify_join(f"node_{i}", "127.0.0.1", 7000 + i)
        # 让 passive 中一个超时
        pid = list(g.passive_view.keys())[0]
        g.passive_view[pid].last_seen = time.time() - g.DEAD_TIMEOUT - 10
        g._cleanup_dead_peers()
        assert pid not in g.passive_view


class TestGossipPeerInfo:
    def test_peer_info_fields(self):
        p = PeerInfo(node_id="node_1", host="127.0.0.1", port=7002)
        assert p.node_id == "node_1"
        assert p.host == "127.0.0.1"
        assert p.port == 7002
        assert p.is_active is True
        assert p.version == "4.1"
        assert p.last_seen > 0


class TestGossipAsyncLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop_as_seed(self):
        g = GossipDiscovery("node_0")
        await g.start()  # 无 seed → 作为种子节点
        assert g._joined is True
        assert g._running is True
        await g.stop()
        assert g._running is False
        assert g.leave_count >= 1

    @pytest.mark.asyncio
    async def test_start_with_seed_peers(self):
        g = GossipDiscovery("node_1")
        await g.start(seed_peers=[("127.0.0.1", 7001)])
        await g.stop()
        assert g.leave_count >= 1

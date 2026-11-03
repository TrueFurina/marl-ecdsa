"""
Gossip 动态节点发现测试
覆盖初始化、动态入网（notify_join）、离线感知（cleanup）、启动/停止
（阶段二：Gossip 动态入网/离线感知增强，MARL-ECDSA 共识链）
"""
import asyncio
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


# --------------------------------------------------------------------------- #
# Shuffle Exchange（gossip 核心操作）
# 2026-10-16 补测：覆盖率报告显示 gossip_discovery 的 shuffle 路径
# （_sample_views / _simulate_peer_view / _do_shuffle / _shuffle_loop）此前
# 无任何单测覆盖（54% → 目标 ≥85%）。以下用例逐条对应行为，非凑数。
# --------------------------------------------------------------------------- #

class TestGossipSampleViews:
    def test_sample_empty_returns_empty(self):
        g = GossipDiscovery("node_0")
        assert g._sample_views() == []

    def test_sample_capped_by_k_view(self):
        g = GossipDiscovery("node_0", k_view=3)
        for i in range(1, 6):
            g.notify_join(f"node_{i}", "127.0.0.1", 7000 + i)
        sample = g._sample_views()
        assert len(sample) == 3
        all_ids = set(g.active_view) | set(g.passive_view)
        assert {p.node_id for p in sample} <= all_ids

    def test_sample_spans_active_and_passive(self):
        """passive-only 时也必须可被采样（active 为空的分支）。"""
        g = GossipDiscovery("node_0", k_view=5)
        for i in range(1, 4):
            g.passive_view[f"node_{i}"] = PeerInfo(
                node_id=f"node_{i}", host="127.0.0.1", port=7000 + i)
        sample = g._sample_views()
        assert len(sample) == 3
        assert {p.node_id for p in sample} == {"node_1", "node_2", "node_3"}


class TestGossipSimulatePeerView:
    def test_simulate_offsets_are_neighbors(self):
        g = GossipDiscovery("node_0", base_port=7001)
        peers = g._simulate_peer_view("node_5")
        # offsets [-2,-1,1,2] ⇒ 3/4/6/7
        assert {p.node_id for p in peers} == {"node_3", "node_4", "node_6", "node_7"}
        ports = {p.node_id: p.port for p in peers}
        assert ports["node_3"] == 7004
        assert ports["node_7"] == 7008

    def test_simulate_excludes_self(self):
        g = GossipDiscovery("node_4")
        peers = g._simulate_peer_view("node_5")   # 邻居含 node_4（自身）⇒ 须剔除
        ids = {p.node_id for p in peers}
        assert "node_4" not in ids
        assert ids == {"node_3", "node_6", "node_7"}

    def test_simulate_wraps_modulo(self):
        g = GossipDiscovery("node_0")
        ids = {p.node_id for p in g._simulate_peer_view("node_1")}  # (1-2)%10 = 9
        assert "node_9" in ids
        assert "node_0" not in ids
        assert ids == {"node_9", "node_2", "node_3"}


class TestGossipDoShuffle:
    @pytest.mark.asyncio
    async def test_do_shuffle_merges_new_peers(self):
        g = GossipDiscovery("node_0", k_view=5, max_peers=20)
        g._joined = True
        g.notify_join("node_1", "127.0.0.1", 7002)      # active 有 node_1
        await g._do_shuffle()
        # peer_num=1 ⇒ 邻居 9/0/2/3，剔除自身 node_0 与已在 active 的 node_2 之外
        # 至少 node_9 / node_3 应进入视图（promote 后可能已在 active）
        known = set(g.active_view) | set(g.passive_view)
        assert {"node_9", "node_3"} <= known
        assert g.shuffle_count == 1

    @pytest.mark.asyncio
    async def test_do_shuffle_empty_active_is_noop(self):
        g = GossipDiscovery("node_0")
        g._joined = True
        await g._do_shuffle()                           # active 为空 ⇒ 直接返回
        assert g.shuffle_count == 0

    @pytest.mark.asyncio
    async def test_do_shuffle_trims_passive_to_max(self, monkeypatch):
        g = GossipDiscovery("node_0", k_view=2, max_peers=2)
        g._joined = True
        g.notify_join("node_1", "127.0.0.1", 7002)      # active 满
        g.notify_join("node_2", "127.0.0.1", 7003)
        for i, ls in ((3, 1.0), (4, 2.0), (5, 3.0)):
            g.passive_view[f"node_{i}"] = PeerInfo(
                node_id=f"node_{i}", host="127.0.0.1", port=7000 + i)
            g.passive_view[f"node_{i}"].last_seen = ls
        # 隔离"合并新 peer"因素，只验证 passive 裁剪行为
        monkeypatch.setattr(g, "_sample_views", lambda: [])
        monkeypatch.setattr(g, "_simulate_peer_view", lambda pid: [])
        await g._do_shuffle()
        assert len(g.passive_view) == 2
        # 最旧的两个（node_3/node_4）应被裁掉，保留 last_seen 最新的
        assert set(g.passive_view) == {"node_4", "node_5"}
        assert g.shuffle_count == 1

    @pytest.mark.asyncio
    async def test_do_shuffle_exception_marks_peer_dead(self, monkeypatch):
        g = GossipDiscovery("node_0", k_view=5)
        g._joined = True
        g.notify_join("node_1", "127.0.0.1", 7002)
        peer = g.active_view["node_1"]

        def _boom():
            raise RuntimeError("simulated shuffle failure")

        monkeypatch.setattr(g, "_sample_views", _boom)   # 在 try 内 ⇒ 走 except 分支
        await g._do_shuffle()                            # 不得向上抛
        assert peer.is_active is False
        assert peer.last_seen == 0.0
        assert g.shuffle_count == 0


class _StopLoop(Exception):
    """中断 _shuffle_loop 的哨兵异常（测试专用）。"""


def _install_sleep_guard(monkeypatch, g, calls):
    """把 asyncio.sleep 换成「第一次正常、第二次抛 _StopLoop」。

    ⚠ 不能把 sleep 换成「直接抛」：`_shuffle_loop` 的 sleep 在**循环开头**，
    直接抛会让循环永远到不了 `_do_shuffle`，于是「应当 shuffle」的用例
    恒真通过（假阳性）。第一次放行才能验证到 `continue`/`_do_shuffle` 分支。
    """
    state = {"n": 0}

    async def _sleep(dt):
        state["n"] += 1
        if state["n"] >= 2:
            raise _StopLoop

    async def _fake_shuffle():
        calls.append(1)

    monkeypatch.setattr(g, "_do_shuffle", _fake_shuffle)
    monkeypatch.setattr(asyncio, "sleep", _sleep)


class TestGossipShuffleLoop:
    @pytest.mark.asyncio
    async def test_shuffle_loop_skips_when_not_joined(self, monkeypatch):
        g = GossipDiscovery("node_0")
        g._running = True                                 # _joined 保持 False
        calls = []
        _install_sleep_guard(monkeypatch, g, calls)
        with pytest.raises(_StopLoop):
            await asyncio.wait_for(g._shuffle_loop(), timeout=1)
        assert calls == []                                # 未入网 ⇒ 不得 shuffle

    @pytest.mark.asyncio
    async def test_shuffle_loop_skips_when_no_active(self, monkeypatch):
        g = GossipDiscovery("node_0")
        g._running = True
        g._joined = True                                  # 已入网但 active 为空
        calls = []
        _install_sleep_guard(monkeypatch, g, calls)
        with pytest.raises(_StopLoop):
            await asyncio.wait_for(g._shuffle_loop(), timeout=1)
        assert calls == []

    @pytest.mark.asyncio
    async def test_shuffle_loop_invokes_do_shuffle(self, monkeypatch):
        g = GossipDiscovery("node_0")
        g._running = True
        g._joined = True
        g.notify_join("node_1", "127.0.0.1", 7002)        # active 非空
        calls = []
        _install_sleep_guard(monkeypatch, g, calls)
        with pytest.raises(_StopLoop):
            await asyncio.wait_for(g._shuffle_loop(), timeout=1)
        assert calls == [1]

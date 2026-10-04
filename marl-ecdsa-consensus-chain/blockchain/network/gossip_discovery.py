"""
Gossip Dynamic Node Discovery Protocol
=======================================
Replaces static P2P neighbor configuration with decentralized dynamic discovery.

⚠️ 实现状态说明（诚实声明）：
  当前版本为**模拟层**——shuffle 交换通过 `_simulate_peer_view()` 本地构造邻居，
  不走真实 P2P 网络传输；`discovery_latency_ms` 因 `_join_start` 在纯模拟路径下
  未设置，实测值 ≈ 0，**不反映真实网络延迟**。
  结构（HyParView 风格的 active/passive view、dead node 检测/清理）是合理的，
  可作为真实 gossip 层的骨架；但演示/答辩时需注明"模拟层，非真实网络测量"，
  避免与真实 P2P 指标混淆。接入真实网络层后此标注应移除。

Key features:
  - Partial View maintenance (HyParView-inspired, O(log n) per node)
  - Periodic shuffle exchanges for membership propagation
  - Automatic dead node detection and eviction
  - Join/leave with bounded convergence time O(log n)

Architecture:
  Each node maintains:
    - active_view: up to K active neighbors (K ≈ log2(N_max))
    - passive_view: up to K passive neighbors (backup for failover)

  Periodic cycle (every T_shuffle seconds):
    1. Select random neighbor from active_view
    2. Exchange view subsets (shuffle operation)
    3. Merge received entries into passive_view
    4. Promote passive→active if active has vacancies

CCF 5th Blockchain Competition | V4.1 | Phase 2 Innovation
"""
import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class PeerInfo:
    """Information about a peer node."""
    node_id: str
    host: str = "127.0.0.1"
    port: int = 7000
    last_seen: float = field(default_factory=time.time)
    version: str = "4.1"
    is_active: bool = True


class GossipDiscovery:
    """
    Decentralized Gossip-based peer discovery.

    Implements a lightweight membership protocol inspired by HyParView
    and Cyclon, adapted for the MARL-ECDSA P2P network layer.

    Usage:
        discovery = GossipDiscovery("node_0", max_peers=20, k_view=5)
        await discovery.start(seed_peers=[("127.0.0.1", 7001)])
        # ... nodes auto-discover each other ...
        peers = discovery.get_active_peers()
    """

    SHUFFLE_INTERVAL = 5.0        # Seconds between shuffle exchanges
    DEAD_TIMEOUT = 30.0           # Seconds before marking peer as dead
    CLEANUP_INTERVAL = 15.0       # Seconds between dead peer cleanup
    JOIN_RETRY_INTERVAL = 2.0     # Seconds between join retries

    def __init__(
        self,
        node_id: str,
        max_peers: int = 20,
        k_view: int = 5,
        base_port: int = 7001,
    ):
        """
        :param node_id: This node's ID
        :param max_peers: Maximum total peers tracked
        :param k_view: Active/passive view size (K ≈ log2(N_max))
        :param base_port: Base port for peer addresses
        """
        self.node_id = node_id
        self.max_peers = max_peers
        self.k_view = k_view
        self.base_port = base_port

        # Views
        self.active_view: Dict[str, PeerInfo] = {}    # Active neighbors
        self.passive_view: Dict[str, PeerInfo] = {}   # Backup neighbors

        # State
        self._running = False
        self._joined = False
        self._tasks: List[asyncio.Task] = []

        # Metrics
        self.join_count: int = 0
        self.leave_count: int = 0
        self.shuffle_count: int = 0
        self.discovery_latency_ms: float = 0.0

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def start(self, seed_peers: Optional[List[Tuple[str, int]]] = None):
        """Start gossip discovery."""
        self._running = True

        if seed_peers:
            # Join via seed nodes
            await self._join(seed_peers)
        else:
            # First node in network — start alone
            self._joined = True
            logger.info(f"[Gossip] {self.node_id}: Started as seed node (no peers)")

        # Background tasks
        self._tasks = [
            asyncio.create_task(self._shuffle_loop()),
            asyncio.create_task(self._cleanup_loop()),
        ]
        logger.info(f"[Gossip] {self.node_id}: Discovery started (K={self.k_view})")

    async def stop(self):
        """Gracefully leave the network."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self.leave_count += 1
        logger.info(f"[Gossip] {self.node_id}: Discovery stopped")

    def get_active_peers(self) -> List[PeerInfo]:
        """Get current active peers."""
        return [p for p in self.active_view.values() if p.is_active]

    def get_peer_count(self) -> int:
        """Get total tracked peers (active + passive)."""
        return len(self.active_view) + len(self.passive_view)

    # -------------------------------------------------------------------------
    # Join Protocol
    # -------------------------------------------------------------------------

    async def _join(self, seed_peers: List[Tuple[str, int]]):
        """Join the network via seed peers."""
        joined = False
        for host, port in seed_peers:
            try:
                # In real implementation: TCP connect → send JOIN_REQ → receive peer list
                # For local simulation: directly populate views
                seed_id = f"node_{port - self.base_port}"

                # Add seed to active view
                self.active_view[seed_id] = PeerInfo(
                    node_id=seed_id, host=host, port=port
                )

                # Simulate receiving forwarded peer list
                for i in range(min(self.k_view - 1, 3)):
                    peer_id = f"node_{(port - self.base_port + i + 1) % 10}"
                    if peer_id != self.node_id and peer_id not in self.active_view:
                        self.passive_view[peer_id] = PeerInfo(
                            node_id=peer_id, host="127.0.0.1",
                            port=self.base_port + int(peer_id.split("_")[1])
                        )

                joined = True
                join_start = getattr(self, '_join_start', time.time())
                self.discovery_latency_ms = (time.time() - join_start) * 1000

                logger.info(
                    f"[Gossip] {self.node_id}: Joined via {seed_id}, "
                    f"discovered {len(self.passive_view)} peers "
                    f"({self.discovery_latency_ms:.1f}ms)"
                )
                break

            except Exception as e:
                logger.debug(f"[Gossip] {self.node_id}: Join via {host}:{port} failed: {e}")
                await asyncio.sleep(self.JOIN_RETRY_INTERVAL)

        if joined:
            self._joined = True
            self.join_count += 1
            # Promote from passive to fill active view
            await self._promote_passive()
        else:
            logger.warning(f"[Gossip] {self.node_id}: Failed to join via any seed peer")

    # -------------------------------------------------------------------------
    # Shuffle Exchange (Core Gossip Operation)
    # -------------------------------------------------------------------------

    async def _shuffle_loop(self):
        """Periodic shuffle exchange loop."""
        while self._running:
            await asyncio.sleep(self.SHUFFLE_INTERVAL)
            if not self._joined or not self.active_view:
                continue

            await self._do_shuffle()

    async def _do_shuffle(self):
        """Execute one shuffle exchange with a random active peer."""
        if not self.active_view:
            return

        # Select random peer from active view
        peer_id = random.choice(list(self.active_view.keys()))
        peer = self.active_view[peer_id]

        try:
            # Simulate shuffle exchange:
            # 1. Send my active+passive view subset to peer
            # 2. Receive peer's view subset
            # 3. Merge into passive view

            my_sample = self._sample_views()
            # In real implementation: await send_shuffle(peer, my_sample)
            #                        response = await recv_shuffle()

            # Simulate receiving peer's view (generate synthetic entries)
            peer_sample = self._simulate_peer_view(peer_id)

            # Merge received entries
            new_peers = 0
            for p_info in peer_sample:
                if p_info.node_id == self.node_id:
                    continue
                if p_info.node_id not in self.active_view and p_info.node_id not in self.passive_view:
                    self.passive_view[p_info.node_id] = p_info
                    new_peers += 1

            # Trim passive view if needed
            while len(self.passive_view) > self.max_peers:
                oldest = min(self.passive_view.keys(),
                            key=lambda k: self.passive_view[k].last_seen)
                del self.passive_view[oldest]

            # Promote from passive to fill active
            await self._promote_passive()

            self.shuffle_count += 1
            if new_peers > 0:
                logger.debug(
                    f"[Gossip] {self.node_id}: Shuffle with {peer_id} — "
                    f"+{new_peers} new peers (active={len(self.active_view)}, "
                    f"passive={len(self.passive_view)})"
                )

        except Exception as e:
            logger.debug(f"[Gossip] {self.node_id}: Shuffle with {peer_id} failed: {e}")
            # Mark peer as potentially dead
            peer.is_active = False
            peer.last_seen = 0.0

    def _sample_views(self) -> List[PeerInfo]:
        """Sample a subset of views to share during shuffle."""
        sample_size = min(self.k_view, len(self.active_view) + len(self.passive_view))
        all_peers = list(self.active_view.values()) + list(self.passive_view.values())
        return random.sample(all_peers, min(sample_size, len(all_peers)))

    def _simulate_peer_view(self, peer_id: str) -> List[PeerInfo]:
        """Simulate receiving a peer's view during shuffle (local simulation)."""
        # In real implementation, this comes from the network
        peer_num = int(peer_id.split("_")[1])
        synthetic = []
        for offset in [-2, -1, 1, 2]:
            neighbor_num = (peer_num + offset) % 10
            neighbor_id = f"node_{neighbor_num}"
            if neighbor_id != self.node_id:
                synthetic.append(PeerInfo(
                    node_id=neighbor_id,
                    host="127.0.0.1",
                    port=self.base_port + neighbor_num,
                ))
        return synthetic

    async def _promote_passive(self):
        """Promote peers from passive to active view."""
        vacancies = self.k_view - len(self.active_view)
        if vacancies <= 0:
            return

        # Promote most recently seen peers
        candidates = sorted(
            self.passive_view.items(),
            key=lambda kv: kv[1].last_seen,
            reverse=True
        )[:vacancies]

        for peer_id, peer_info in candidates:
            self.active_view[peer_id] = peer_info
            del self.passive_view[peer_id]

    # -------------------------------------------------------------------------
    # Dead Node Detection & Cleanup
    # -------------------------------------------------------------------------

    async def _cleanup_loop(self):
        """Periodic dead peer cleanup."""
        while self._running:
            await asyncio.sleep(self.CLEANUP_INTERVAL)
            self._cleanup_dead_peers()

    def _cleanup_dead_peers(self):
        """Remove peers that haven't been seen recently."""
        now = time.time()
        dead_active = [
            pid for pid, p in self.active_view.items()
            if now - p.last_seen > self.DEAD_TIMEOUT
        ]
        dead_passive = [
            pid for pid, p in self.passive_view.items()
            if now - p.last_seen > self.DEAD_TIMEOUT
        ]

        for pid in dead_active:
            logger.info(f"[Gossip] {self.node_id}: Removing dead peer {pid} from active")
            # Move to passive first (may come back)
            self.passive_view[pid] = self.active_view[pid]
            self.passive_view[pid].is_active = False
            del self.active_view[pid]

        for pid in dead_passive:
            del self.passive_view[pid]

        if dead_active or dead_passive:
            logger.debug(
                f"[Gossip] {self.node_id}: Cleaned {len(dead_active)} active + "
                f"{len(dead_passive)} passive dead peers"
            )

    # -------------------------------------------------------------------------
    # Node Join/Leave Notification
    # -------------------------------------------------------------------------

    def notify_join(self, new_node_id: str, host: str = "127.0.0.1", port: int = 7000):
        """Notify discovery of a new node joining."""
        if new_node_id == self.node_id:
            return
        peer = PeerInfo(node_id=new_node_id, host=host, port=port)
        if len(self.active_view) < self.k_view:
            self.active_view[new_node_id] = peer
        else:
            self.passive_view[new_node_id] = peer
        logger.info(f"[Gossip] {self.node_id}: New peer detected: {new_node_id}")

    def notify_leave(self, node_id: str):
        """Notify discovery of a node leaving."""
        if node_id in self.active_view:
            self.active_view[node_id].is_active = False
            self.passive_view[node_id] = self.active_view.pop(node_id)
        elif node_id in self.passive_view:
            self.passive_view[node_id].is_active = False
        logger.info(f"[Gossip] {self.node_id}: Peer left: {node_id}")

    # -------------------------------------------------------------------------
    # Statistics
    # -------------------------------------------------------------------------

    def get_stats(self) -> Dict:
        """Get discovery protocol statistics.

        ⚠️ 注：模拟层下 `discovery_latency_ms` 实测 ≈ 0，不反映真实网络延迟。
        """
        return {
            "node_id": self.node_id,
            "active_peers": len(self.active_view),
            "passive_peers": len(self.passive_view),
            "total_peers": self.get_peer_count(),
            "shuffle_count": self.shuffle_count,
            "join_count": self.join_count,
            "leave_count": self.leave_count,
            "discovery_latency_ms": round(self.discovery_latency_ms, 2),
            "k_view": self.k_view,
            "max_peers": self.max_peers,
            "active_peer_ids": list(self.active_view.keys()),
        }


# =============================================================================
# Demo
# =============================================================================
async def demo_gossip_network():
    """Demonstrate Gossip discovery with 5 simulated nodes."""
    print("=" * 60)
    print("Gossip Dynamic Node Discovery — Demo")
    print("=" * 60)

    # Node 0 starts alone (seed)
    node0 = GossipDiscovery("node_0", max_peers=20, k_view=5, base_port=7001)
    await node0.start()  # No seed peers = first node
    print(f"\nNode 0 started (seed): {node0.get_stats()['active_peers']} active peers")

    # Nodes 1-4 join via node 0
    nodes = [node0]
    for i in range(1, 5):
        node = GossipDiscovery(f"node_{i}", max_peers=20, k_view=5, base_port=7001)
        await node.start(seed_peers=[("127.0.0.1", 7001)])
        nodes.append(node)
        print(f"Node {i} joined: {node.get_stats()['active_peers']} active peers "
              f"({node.get_stats()['discovery_latency_ms']}ms)")

    # Let gossip propagate
    print("\nRunning 3 shuffle cycles...")
    for cycle in range(3):
        await asyncio.sleep(0.1)  # Simulate shuffle interval
        for i, node in enumerate(nodes):
            await node._do_shuffle()
        total_peers = sum(n.get_peer_count() for n in nodes)
        print(f"  Cycle {cycle + 1}: total tracked peers across network = {total_peers}")

    # Show convergence
    print(f"\nConvergence after 3 cycles:")
    for node in nodes:
        stats = node.get_stats()
        print(f"  {stats['node_id']}: active={stats['active_peers']}, "
              f"passive={stats['passive_peers']}, shuffles={stats['shuffle_count']}")

    # Simulate node 3 going offline
    print(f"\nSimulating node_3 offline...")
    nodes[3].notify_leave("node_3")
    await asyncio.sleep(0.1)
    for node in nodes:
        node._cleanup_dead_peers()
    print(f"After cleanup — node 0 active peers: {nodes[0].get_stats()['active_peers']}")

    # Cleanup
    for node in nodes:
        await node.stop()

    print("\n✅ Gossip discovery demo complete!")
    print(f"   Protocol: HyParView-inspired Partial View")
    print(f"   View size K: 5")
    print(f"   Convergence: O(log n) gossip cycles")
    print(f"   Dead detection timeout: 30s")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    asyncio.run(demo_gossip_network())

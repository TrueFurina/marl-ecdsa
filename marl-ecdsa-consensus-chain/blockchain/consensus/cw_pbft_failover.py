"""
CW-PBFT Dynamic Primary Failover Extension
===========================================
Extends CWPBFTConsensus with:
  1. Dynamic primary node failure detection
  2. Byzantine primary simulation (malicious proposer scenarios)
  3. Automatic view change + primary rotation on timeout
  4. Failover latency quantification

CCF 5th Blockchain Competition | V4.1 | Consensus Module Extension

Usage:
    from blockchain.consensus.cw_pbft_failover import CWPBFTConsensusWithFailover
    consensus = CWPBFTConsensusWithFailover("node_0", node_ids)
    consensus.simulated_consensus_with_failover(block_hash, proposer)
"""
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .cw_pbft import CWPBFTConsensus, ConsensusState, ConsensusVote

logger = logging.getLogger(__name__)


class PrimaryStatus(str, Enum):
    HEALTHY = "healthy"
    TIMEOUT = "timeout"
    BYZANTINE = "byzantine"
    OFFLINE = "offline"


@dataclass
class FailoverRecord:
    """Record of a single failover event."""
    timestamp: int
    failed_primary: str
    new_primary: str
    reason: str
    view_number: int
    failover_latency_ms: float
    consensus_recovered: bool


class CWPBFTConsensusWithFailover(CWPBFTConsensus):
    """
    CW-PBFT with dynamic primary failover.

    Extends the base CWPBFTConsensus class with:
    - Primary health monitoring via heartbeat timeout
    - Byzantine primary detection (contradictory proposals)
    - Automatic view change triggering consensus re-election
    - Failover event logging for quantitative analysis
    """

    HEARTBEAT_TIMEOUT_MS = 3000       # 3s primary heartbeat timeout
    VIEW_CHANGE_TIMEOUT_MS = 2000     # 2s view change timeout
    MAX_VIEW_CHANGES = 3              # Max consecutive view changes before stall

    def __init__(self, node_id: str, consensus_nodes: List[str]):
        super().__init__(node_id, consensus_nodes)
        # Failover state
        self._primary_status: Dict[str, PrimaryStatus] = {
            nid: PrimaryStatus.HEALTHY for nid in consensus_nodes
        }
        self._last_heartbeat: Dict[str, int] = {}
        self._failover_history: List[FailoverRecord] = []
        self._view_change_count: int = 0
        self._current_view: int = 0
        # Byzantine detection
        # Key: (primary_id, block_height) → block_hash
        # Only same height with different hash → byzantine
        self._proposal_history: Dict[Tuple[str, int], str] = {}
        self._byzantine_primaries: set = set()

    # -------------------------------------------------------------------------
    # Primary Health Monitoring
    # -------------------------------------------------------------------------

    def record_heartbeat(self, node_id: str):
        """Record a heartbeat from a node (keeps primary status healthy)."""
        self._last_heartbeat[node_id] = int(time.time() * 1000)
        if node_id in self._primary_status:
            self._primary_status[node_id] = PrimaryStatus.HEALTHY

    def check_primary_health(self, primary_id: str) -> PrimaryStatus:
        """Check if the current primary is healthy."""
        now_ms = int(time.time() * 1000)
        last_hb = self._last_heartbeat.get(primary_id, 0)

        if primary_id in self._byzantine_primaries:
            return PrimaryStatus.BYZANTINE

        if now_ms - last_hb > self.HEARTBEAT_TIMEOUT_MS:
            self._primary_status[primary_id] = PrimaryStatus.TIMEOUT
            return PrimaryStatus.TIMEOUT

        return PrimaryStatus.HEALTHY

    # -------------------------------------------------------------------------
    # Byzantine Primary Detection
    # -------------------------------------------------------------------------

    def detect_byzantine_primary(self, primary_id: str, block_hash: str, block_height: int) -> bool:
        """
        Detect if primary is proposing contradictory blocks.

        Byzantine behavior: same primary proposes different block hashes
        for the SAME block height (equivocation).

        Normal operation: each round produces a new hash for a new height,
        which is NOT byzantine.

        :param primary_id: The primary node proposing the block
        :param block_hash: The hash of the proposed block
        :param block_height: The height of the proposed block
        :return: True if byzantine behavior detected, False otherwise
        """
        key = (primary_id, block_height)

        if key not in self._proposal_history:
            # First proposal for this (primary, height) — record and continue
            self._proposal_history[key] = block_hash
            self._cleanup_old_proposals(block_height)
            return False

        existing_hash = self._proposal_history[key]
        if existing_hash != block_hash:
            # Same height, different hash → genuine byzantine equivocation
            logger.warning(
                f"[CW-PBFT-Failover] ⚠️ Byzantine primary detected: "
                f"{primary_id} proposed conflicting blocks at height {block_height}! "
                f"Previous: {existing_hash[:16]}... New: {block_hash[:16]}..."
            )
            self._byzantine_primaries.add(primary_id)
            self._primary_status[primary_id] = PrimaryStatus.BYZANTINE
            return True

        # Same height, same hash → duplicate/retransmit, not byzantine
        return False

    def _cleanup_old_proposals(self, current_height: int, keep: int = 10):
        """
        Remove proposal history entries older than `keep` heights
        to bound memory usage.

        :param current_height: The latest block height being processed
        :param keep: Number of recent heights to retain (default 10)
        """
        if len(self._proposal_history) <= keep:
            return
        cutoff = current_height - keep
        # Delete entries whose height is older than the cutoff
        keys_to_remove = [k for k in self._proposal_history if k[1] < cutoff]
        for k in keys_to_remove:
            del self._proposal_history[k]

    # -------------------------------------------------------------------------
    # View Change Protocol
    # -------------------------------------------------------------------------

    def trigger_view_change(self, failed_primary: str, reason: str) -> Optional[str]:
        """
        Trigger view change to elect a new primary.

        Returns the new primary ID, or None if max view changes exceeded.
        """
        if self._view_change_count >= self.MAX_VIEW_CHANGES:
            logger.error(
                f"[CW-PBFT-Failover] ❌ Max view changes ({self.MAX_VIEW_CHANGES}) "
                f"exceeded! Consensus stalled."
            )
            return None

        self._view_change_count += 1
        self._current_view += 1

        # Select new primary: next healthy node in rotation
        old_idx = self.consensus_nodes.index(failed_primary) if failed_primary in self.consensus_nodes else 0
        new_idx = (old_idx + self._current_view) % self.n

        # Skip known byzantine/timeout nodes
        attempts = 0
        while attempts < self.n:
            candidate = self.consensus_nodes[new_idx]
            status = self._primary_status.get(candidate, PrimaryStatus.HEALTHY)

            if status in (PrimaryStatus.HEALTHY,):
                logger.info(
                    f"[CW-PBFT-Failover] View change: {failed_primary}({reason}) "
                    f"→ {candidate} (view={self._current_view})"
                )
                return candidate

            new_idx = (new_idx + 1) % self.n
            attempts += 1

        logger.error("[CW-PBFT-Failover] ❌ No healthy node available for primary!")
        return None

    # -------------------------------------------------------------------------
    # Consensus with Failover
    # -------------------------------------------------------------------------

    def simulated_consensus_with_failover(
        self,
        block_hash: str,
        proposer: str,
        block_height: int = 0,
        simulate_byzantine: bool = False,
        simulate_timeout: bool = False,
    ) -> Tuple[bool, Optional[FailoverRecord]]:
        """
        Run simulated consensus with failover logic.

        :param block_hash: Block hash to achieve consensus on
        :param proposer: Proposed primary node
        :param block_height: Block height (for byzantine detection)
        :param simulate_byzantine: Force the proposer to act Byzantine
        :param simulate_timeout: Force the proposer to timeout
        :return: (consensus_success, failover_record)
        """
        failover_record = None
        actual_proposer = proposer

        # Step 1: Check primary health
        if simulate_timeout:
            self._primary_status[proposer] = PrimaryStatus.TIMEOUT
            logger.info(f"[CW-PBFT-Failover] Simulated timeout for {proposer}")

        if simulate_byzantine:
            self._byzantine_primaries.add(proposer)
            self._primary_status[proposer] = PrimaryStatus.BYZANTINE
            logger.info(f"[CW-PBFT-Failover] Simulated Byzantine behavior for {proposer}")

        health = self.check_primary_health(proposer)

        # Step 2: If primary unhealthy, trigger view change
        if health != PrimaryStatus.HEALTHY:
            failover_start = time.perf_counter()
            reason = f"primary_{health.value}"
            new_primary = self.trigger_view_change(proposer, reason)

            if new_primary is None:
                return False, None

            actual_proposer = new_primary
            failover_latency = (time.perf_counter() - failover_start) * 1000

            failover_record = FailoverRecord(
                timestamp=int(time.time() * 1000),
                failed_primary=proposer,
                new_primary=new_primary,
                reason=reason,
                view_number=self._current_view,
                failover_latency_ms=round(failover_latency, 2),
                consensus_recovered=False,  # Set after consensus attempt
            )
            self._failover_history.append(failover_record)

        # Step 3: Byzantine primary detection
        if not simulate_byzantine:
            is_byz = self.detect_byzantine_primary(actual_proposer, block_hash, block_height)
            if is_byz:
                new_primary = self.trigger_view_change(actual_proposer, "byzantine_detected")
                if new_primary:
                    actual_proposer = new_primary

        # Step 4: Run consensus with the (possibly new) primary
        consensus_ok = self.simulated_consensus(block_hash, actual_proposer)

        # Step 5: Update failover record
        if failover_record:
            failover_record.consensus_recovered = consensus_ok
            self._failover_history[-1] = failover_record

        # Step 6: Reset view change counter on success
        if consensus_ok:
            self._view_change_count = 0

        return consensus_ok, failover_record

    # -------------------------------------------------------------------------
    # Byzantine Scenario Simulation
    # -------------------------------------------------------------------------

    def simulate_byzantine_primary_attack(self, n_rounds: int = 20) -> Dict:
        """
        Simulate multiple consensus rounds with intermittent Byzantine primaries.

        Returns quantification of failover effectiveness.
        """
        results = {
            "total_rounds": n_rounds,
            "byzantine_events": 0,
            "successful_failovers": 0,
            "failed_consensus": 0,
            "avg_failover_latency_ms": 0.0,
            "failover_records": [],
        }

        latencies = []
        for r in range(n_rounds):
            block_hash = f"byzantine_test_{r:04d}"
            proposer = self.get_primary(r)

            # Every 5th primary is Byzantine
            is_byzantine = (r % 5 == 0 and r > 0)

            ok, record = self.simulated_consensus_with_failover(
                block_hash, proposer,
                block_height=r,
                simulate_byzantine=is_byzantine,
            )

            if is_byzantine:
                results["byzantine_events"] += 1

            if record:
                results["successful_failovers"] += 1
                latencies.append(record.failover_latency_ms)
                results["failover_records"].append({
                    "round": r,
                    "failed_primary": record.failed_primary,
                    "new_primary": record.new_primary,
                    "latency_ms": record.failover_latency_ms,
                    "recovered": record.consensus_recovered,
                })

            if not ok:
                results["failed_consensus"] += 1
                self.reset()

        if latencies:
            results["avg_failover_latency_ms"] = round(sum(latencies) / len(latencies), 2)

        logger.info(
            f"[CW-PBFT-Failover] Byzantine simulation complete: "
            f"{results['byzantine_events']} attacks, "
            f"{results['successful_failovers']} failovers, "
            f"avg latency={results['avg_failover_latency_ms']}ms"
        )
        return results

    # -------------------------------------------------------------------------
    # Statistics & Reporting
    # -------------------------------------------------------------------------

    def get_failover_stats(self) -> Dict:
        """Get comprehensive failover statistics."""
        return {
            "total_failovers": len(self._failover_history),
            "view_change_count": self._view_change_count,
            "current_view": self._current_view,
            "byzantine_primaries_detected": len(self._byzantine_primaries),
            "primary_status": {k: v.value for k, v in self._primary_status.items()},
            "recent_failovers": [
                {
                    "failed": f.failed_primary,
                    "new": f.new_primary,
                    "reason": f.reason,
                    "latency_ms": f.failover_latency_ms,
                    "recovered": f.consensus_recovered,
                }
                for f in self._failover_history[-5:]
            ],
            "failover_success_rate": round(
                sum(1 for f in self._failover_history if f.consensus_recovered) /
                max(1, len(self._failover_history)) * 100, 1
            ),
        }

    def reset_failover_state(self):
        """Reset failover state (for test repeatability)."""
        self._primary_status = {nid: PrimaryStatus.HEALTHY for nid in self.consensus_nodes}
        self._last_heartbeat.clear()
        self._failover_history.clear()
        self._view_change_count = 0
        self._current_view = 0
        self._proposal_history.clear()
        self._byzantine_primaries.clear()


# =============================================================================
# Quick Test
# =============================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    print("=" * 60)
    print("CW-PBFT Dynamic Failover — Integration Test")
    print("=" * 60)

    nodes = [f"node_{i}" for i in range(5)]
    consensus = CWPBFTConsensusWithFailover("node_0", nodes)

    # Set weights
    for i, nid in enumerate(nodes):
        consensus.update_weight(nid, 1.0 + 0.5 * (i / 4))

    # Test 1: Normal consensus (no failover)
    print("\n1. Normal consensus (no Byzantine)...")
    ok, record = consensus.simulated_consensus_with_failover("hash_normal", "node_0", block_height=0)
    print(f"   Result: {'PASS' if ok else 'FAIL'}, failover={'Yes' if record else 'No'}")

    # Test 2: Byzantine primary simulation
    print("\n2. Byzantine primary simulation...")
    results = consensus.simulate_byzantine_primary_attack(n_rounds=20)
    print(f"   Byzantine events: {results['byzantine_events']}")
    print(f"   Successful failovers: {results['successful_failovers']}")
    print(f"   Failed consensus: {results['failed_consensus']}")
    print(f"   Avg failover latency: {results['avg_failover_latency_ms']}ms")

    # Test 3: Stats
    print("\n3. Failover Statistics:")
    stats = consensus.get_failover_stats()
    for k, v in stats.items():
        if k != "recent_failovers":
            print(f"   {k}: {v}")

    print("\n✅ CW-PBFT failover integration test complete!")

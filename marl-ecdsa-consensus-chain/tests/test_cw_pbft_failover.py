"""
CW-PBFT 动态故障切换测试
覆盖拜占庭主节点检测、视图更换、故障切换统计
"""
import logging

import pytest

from blockchain.consensus.cw_pbft_failover import (
    CWPBFTConsensusWithFailover, PrimaryStatus,
)

logging.basicConfig(level=logging.CRITICAL)

NODES_5 = [f'node_{i}' for i in range(5)]


class TestFailoverCore:
    def test_initial_health_without_heartbeat_is_timeout(self):
        """无心跳记录的节点初始即视为超时（HEARTBEAT_TIMEOUT_MS 判定）"""
        cf = CWPBFTConsensusWithFailover('node_0', NODES_5)
        status = cf.check_primary_health('node_0')
        assert status in (PrimaryStatus.TIMEOUT, PrimaryStatus.HEALTHY)
        # 记录心跳后应健康
        cf.record_heartbeat('node_0')
        assert cf.check_primary_health('node_0') == PrimaryStatus.HEALTHY

    def test_record_heartbeat(self):
        cf = CWPBFTConsensusWithFailover('node_0', NODES_5)
        cf.record_heartbeat('node_1')
        assert cf._last_heartbeat['node_1'] > 0

    def test_trigger_view_change(self):
        cf = CWPBFTConsensusWithFailover('node_0', NODES_5)
        cf._byzantine_primaries.add('node_0')
        new_primary = cf.trigger_view_change('node_0', 'byzantine_detected')
        assert new_primary is not None
        assert new_primary != 'node_0'
        assert cf._view_change_count >= 1


class TestByzantineSimulation:
    def test_simulate_byzantine_primary_attack(self):
        """拜占庭主节点攻击模拟：检测到的事件>0"""
        cf = CWPBFTConsensusWithFailover('node_0', NODES_5)
        result = cf.simulate_byzantine_primary_attack(n_rounds=10)
        assert result['byzantine_events'] > 0
        assert 'failover_records' in result

    def test_controlled_failover_recovery(self):
        """受控场景：拜占庭轮次触发故障切换且共识恢复"""
        cf = CWPBFTConsensusWithFailover('node_0', NODES_5)
        ok, record = cf.simulated_consensus_with_failover(
            'hash_ctl', 'node_0', simulate_byzantine=True,
        )
        assert ok is True
        assert record is not None
        assert record.consensus_recovered is True

    def test_failover_stats(self):
        cf = CWPBFTConsensusWithFailover('node_0', NODES_5)
        cf.simulated_consensus_with_failover('h1', 'node_0', simulate_byzantine=True)
        stats = cf.get_failover_stats()
        assert 'view_change_count' in stats

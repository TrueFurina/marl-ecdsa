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
    def test_initial_health_without_heartbeat_is_unknown(self):
        """无心跳记录：信息缺失 ⇒ UNKNOWN，绝不据此误判 TIMEOUT（2026-11-02 修复）。

        旧实现 last_hb 缺省为 0，`now-0` 恒大于超时阈值，于是刚初始化的合法
        主节点也被判 TIMEOUT 并凭空触发 failover（与自测注释"no failover"相悖）。
        """
        cf = CWPBFTConsensusWithFailover('node_0', NODES_5)
        assert cf.check_primary_health('node_0') == PrimaryStatus.UNKNOWN
        # 记录心跳后应健康
        cf.record_heartbeat('node_0')
        assert cf.check_primary_health('node_0') == PrimaryStatus.HEALTHY

    def test_stale_heartbeat_is_timeout(self):
        """收到过心跳但已超时 ⇒ TIMEOUT（保留真实超时检测能力）。"""
        cf = CWPBFTConsensusWithFailover('node_0', NODES_5)
        cf.record_heartbeat('node_0')
        # 伪造一条"很久以前"的心跳（timestamp=1ms，必已超时）
        cf._last_heartbeat['node_0'] = 1
        assert cf.check_primary_health('node_0') == PrimaryStatus.TIMEOUT

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


# --------------------------------------------------------------------------- #
# 2026-10-16 补测（覆盖率报告显示本文件此前 70%）：
#   1) detect_byzantine_primary 的「同高度不同哈希 ⇒ 拜占庭等价」——这是
#      **安全关键路径**，此前完全无覆盖（只有 simulate_byzantine 强制注入）。
#   2) _cleanup_old_proposals 的内存上界、trigger_view_change 的两条
#      失败分支（达上限 / 无健康节点）、simulate_timeout 路径、reset。
# --------------------------------------------------------------------------- #

class TestByzantinePrimaryEquivocation:
    """真实等价（equivocation）检测：同一主节点在同一高度提出不同区块。"""

    def test_first_proposal_recorded_not_byzantine(self):
        cf = CWPBFTConsensusWithFailover('node_0', NODES_5)
        assert cf.detect_byzantine_primary('node_0', 'hash_a', 5) is False
        assert cf._proposal_history[('node_0', 5)] == 'hash_a'

    def test_same_height_same_hash_retransmit_not_byzantine(self):
        """同高度同哈希 = 重复/重传，不得误判为拜占庭（防误报）。"""
        cf = CWPBFTConsensusWithFailover('node_0', NODES_5)
        assert cf.detect_byzantine_primary('node_1', 'hash_x', 3) is False
        assert cf.detect_byzantine_primary('node_1', 'hash_x', 3) is False
        assert 'node_1' not in cf._byzantine_primaries

    def test_same_height_different_hash_is_equivocation(self):
        """同高度不同哈希 = 真拜占庭等价（本类的核心断言）。"""
        cf = CWPBFTConsensusWithFailover('node_0', NODES_5)
        assert cf.detect_byzantine_primary('node_0', 'hash_A', 7) is False
        assert cf.detect_byzantine_primary('node_0', 'hash_B', 7) is True
        assert 'node_0' in cf._byzantine_primaries
        assert cf._primary_status['node_0'] == PrimaryStatus.BYZANTINE

    def test_different_height_same_hash_not_byzantine(self):
        """每轮新高度产生新哈希属正常行为，不得误判。"""
        cf = CWPBFTConsensusWithFailover('node_0', NODES_5)
        assert cf.detect_byzantine_primary('node_2', 'hash_y', 1) is False
        assert cf.detect_byzantine_primary('node_2', 'hash_y', 2) is False
        assert 'node_2' not in cf._byzantine_primaries

    def test_proposal_history_bounded_after_cleanup(self):
        """proposal_history 必须有内存上界（keep=10 ⇒ 至多 11 条）。"""
        cf = CWPBFTConsensusWithFailover('node_0', NODES_5)
        for h in range(30):
            cf.detect_byzantine_primary('node_0', f'h{h}', h)
        assert len(cf._proposal_history) <= 11
        heights = sorted(k[1] for k in cf._proposal_history)
        assert heights[0] >= 19          # 只保留最近 10 个高度


class TestViewChangeLimits:
    def test_view_change_returns_none_at_max(self):
        """达到 MAX_VIEW_CHANGES 后必须停下（防无限视图更换）。"""
        cf = CWPBFTConsensusWithFailover('node_0', NODES_5)
        cf._view_change_count = cf.MAX_VIEW_CHANGES
        assert cf.trigger_view_change('node_0', 'stalled') is None
        assert cf._view_change_count == cf.MAX_VIEW_CHANGES

    def test_view_change_returns_none_when_no_healthy(self):
        """所有节点均不健康 ⇒ 无可用主节点，返回 None（而非误选）。"""
        cf = CWPBFTConsensusWithFailover('node_0', NODES_5)
        for nid in NODES_5:
            cf._primary_status[nid] = PrimaryStatus.BYZANTINE
        assert cf.trigger_view_change('node_0', 'all_down') is None

    def test_view_change_picks_different_node(self):
        cf = CWPBFTConsensusWithFailover('node_0', NODES_5)
        cf._primary_status['node_0'] = PrimaryStatus.TIMEOUT
        new_primary = cf.trigger_view_change('node_0', 'timeout')
        assert new_primary is not None
        assert new_primary != 'node_0'
        assert cf._view_change_count == 1
        assert cf._current_view == 1


class TestFailoverPaths:
    def test_simulate_timeout_triggers_failover(self):
        cf = CWPBFTConsensusWithFailover('node_0', NODES_5)
        ok, record = cf.simulated_consensus_with_failover(
            'hash_t', 'node_0', simulate_timeout=True)
        assert ok is True
        assert record is not None
        assert record.failed_primary == 'node_0'
        assert record.reason == 'primary_timeout'
        assert record.new_primary != 'node_0'
        assert record.consensus_recovered is True

    def test_simulate_byzantine_triggers_failover(self):
        cf = CWPBFTConsensusWithFailover('node_0', NODES_5)
        ok, record = cf.simulated_consensus_with_failover(
            'hash_b', 'node_0', simulate_byzantine=True, block_height=3)
        assert ok is True
        assert record.reason == 'primary_byzantine'
        assert record.consensus_recovered is True

    def test_view_change_counter_resets_on_success(self):
        """Step 6 语义：共识成功后视图更换计数归零（可复现的关键）。"""
        cf = CWPBFTConsensusWithFailover('node_0', NODES_5)
        cf.simulated_consensus_with_failover('h1', 'node_0', simulate_timeout=True)
        assert cf._view_change_count == 0

    def test_reset_failover_state_clears_everything(self):
        cf = CWPBFTConsensusWithFailover('node_0', NODES_5)
        cf.simulated_consensus_with_failover('h1', 'node_0', simulate_byzantine=True)
        cf._proposal_history[('node_0', 0)] = 'h'
        cf.reset_failover_state()
        assert cf._view_change_count == 0
        assert cf._current_view == 0
        assert cf._failover_history == []
        assert cf._proposal_history == {}
        assert cf._byzantine_primaries == set()
        assert all(s == PrimaryStatus.HEALTHY for s in cf._primary_status.values())

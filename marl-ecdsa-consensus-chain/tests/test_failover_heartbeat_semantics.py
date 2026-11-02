"""故障切换心跳语义回归锁（2026-11-03）

缺陷形态：`_last_heartbeat` 是空 dict，`check_primary_health` 用
`self._last_heartbeat.get(primary_id, 0)` 取缺省值 —— 0 被当成「纪元 0 发过
心跳」，于是 `now_ms - 0 > HEARTBEAT_TIMEOUT_MS` 恒真，**从未发过心跳的节点
一律被判超时**。

后果：全新引擎的第一轮（以及模拟循环里的每一轮，因为模拟里没人补心跳）都会
触发一次虚假视图切换。实测 `simulate_byzantine_primary_attack(n_rounds=20)`
在只注入 3 次拜占庭的情况下报告 `successful_failovers = 20`（100%）—— 故障
切换统计与真实拜占庭事件完全脱钩，而这正是论文用来量化 failover 有效性的数据。

修复：心跳表在构造/重置时以当前时刻初始化；`check_primary_health` 把「从未
收到心跳」解释为「监控刚开始」，给一个 `HEARTBEAT_TIMEOUT_MS` 宽限期，宽限期
后仍无心跳才判超时。

本文件锁住四件事：
1. 全新引擎的健康 primary 不被判超时（不误报）；
2. 正常轮不触发视图切换（failover 记录为 None）；
3. 真正超时（心跳过旧）仍被判超时（不误放）；
4. 重置后不会退回到「一律超时」的旧行为。
"""
import logging
import time

from blockchain.consensus.cw_pbft_failover import (
    CWPBFTConsensusWithFailover, PrimaryStatus,
)

logging.basicConfig(level=logging.CRITICAL)

NODES_5 = [f'node_{i}' for i in range(5)]


def _engine():
    return CWPBFTConsensusWithFailover('node_0', NODES_5)


class TestFreshEngineHealth:
    def test_fresh_engine_primary_is_healthy(self):
        """全新引擎：健康 primary 不得被判超时"""
        cf = _engine()
        assert cf.check_primary_health('node_0') == PrimaryStatus.HEALTHY

    def test_all_nodes_initialized_in_heartbeat_table(self):
        """构造时心跳表已按节点初始化（不是空表）"""
        cf = _engine()
        assert set(cf._last_heartbeat) == set(NODES_5)
        assert all(ts > 0 for ts in cf._last_heartbeat.values())

    def test_unknown_node_starts_monitoring(self):
        """运行期首次问到的节点：从此刻开始计时并视为健康"""
        cf = _engine()
        assert cf.check_primary_health('node_x') == PrimaryStatus.HEALTHY
        assert cf._last_heartbeat['node_x'] > 0


class TestNoSpuriousFailover:
    def test_normal_round_does_not_trigger_failover(self):
        """正常轮（主节点健康）不得产生 failover 记录"""
        cf = _engine()
        ok, record = cf.simulated_consensus_with_failover(
            'hash_normal', 'node_0', block_height=0,
        )
        assert ok is True
        assert record is None
        assert cf._failover_history == []

    def test_normal_round_after_explicit_heartbeat(self):
        """显式补心跳后同样不触发切换（两种来源语义一致）"""
        cf = _engine()
        for nid in NODES_5:
            cf.record_heartbeat(nid)
        ok, record = cf.simulated_consensus_with_failover(
            'hash_hb', 'node_0', block_height=1,
        )
        assert ok is True
        assert record is None


class TestGenuineTimeoutStillDetected:
    def test_stale_heartbeat_is_timeout(self):
        """心跳过旧仍判超时（防止修复把真故障放过去）"""
        cf = _engine()
        cf._last_heartbeat['node_0'] = int(time.time() * 1000) - 10_000
        assert cf.check_primary_health('node_0') == PrimaryStatus.TIMEOUT

    def test_byzantine_primary_still_triggers_failover(self):
        """注入拜占庭仍会切换主节点（防止修复造成漏报）"""
        cf = _engine()
        ok, record = cf.simulated_consensus_with_failover(
            'hash_byz', 'node_0', simulate_byzantine=True,
        )
        assert ok is True
        assert record is not None
        assert record.failed_primary == 'node_0'
        assert record.new_primary != 'node_0'
        assert record.consensus_recovered is True


class TestResetSemantics:
    def test_reset_reinitializes_heartbeat_table(self):
        """重置后心跳表重新初始化，不退回到「一律超时」"""
        cf = _engine()
        cf._last_heartbeat['node_0'] = 0          # 人为制造旧状态
        cf.reset_failover_state()
        assert cf._last_heartbeat['node_0'] > 0
        assert cf.check_primary_health('node_0') == PrimaryStatus.HEALTHY

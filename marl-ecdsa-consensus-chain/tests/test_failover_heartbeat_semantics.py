"""故障切换心跳语义回归锁（2026-11-03，2026-11-03 二次修订）

缺陷形态：`_last_heartbeat` 是空 dict，`check_primary_health` 用
`self._last_heartbeat.get(primary_id, 0)` 取缺省值 —— 0 被当成「纪元 0 发过
心跳」，于是 `now_ms - 0 > HEARTBEAT_TIMEOUT_MS` 恒真，**从未发过心跳的节点
一律被判超时**。

后果：全新引擎的第一轮（以及模拟循环里的每一轮，因为模拟里没人补心跳）都会
触发一次虚假视图切换。实测 `simulate_byzantine_primary_attack(n_rounds=20)`
在只注入 3 次拜占庭的情况下报告 `successful_failovers = 20`（100%）—— 故障
切换统计与真实拜占庭事件完全脱钩，而这正是论文用来量化 failover 有效性的数据。

修复的最终口径（**以本文件为准，勿回退**）：
  「从未收到心跳」既不是「健康」也不是「超时」，而是 **UNKNOWN** ——
  信息缺失不等于任何一侧的事实。`_last_heartbeat` 保持空表，不伪造时间戳；
  `check_primary_health` 对表外节点直接返回 UNKNOWN，且**不改写**
  `_primary_status`（保持可信任候选），因此不会触发视图切换。

  为什么不选「构造时把表按 now 初始化、一律判 HEALTHY」（2026-11-03 首版）：
  那等于对「从未收到心跳」的节点**声称**它刚刚发过心跳 —— 状态表撒谎，
  持久化/审计时无法区分「真健康」与「没消息」。两种写法在「正常轮不触发切换」
  上等价（见 TestNoSpuriousFailover），但 UNKNOWN 多保留一个真实状态。

本文件锁住四件事：
1. 全新引擎的健康 primary 不被**误判超时**，而是 UNKNOWN（不误报）；
2. 心跳表初始为空，不得伪造时间戳；
3. 真正超时（心跳过旧）仍被判超时（不误放）；拜占庭仍触发切换；
4. 重置后不退回到「一律超时」的旧行为。
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
    def test_fresh_engine_primary_is_unknown_not_timeout(self):
        """全新引擎：从未收到心跳 ⇒ UNKNOWN。

        关键在**不等于 TIMEOUT** —— 旧实现的缺陷正是 `now - 0 > 阈值` 恒真。
        """
        cf = _engine()
        assert cf.check_primary_health('node_0') == PrimaryStatus.UNKNOWN
        assert cf.check_primary_health('node_0') != PrimaryStatus.TIMEOUT

    def test_heartbeat_table_starts_empty(self):
        """构造时心跳表为空：不伪造「刚刚发过」的时间戳"""
        cf = _engine()
        assert cf._last_heartbeat == {}, (
            f"心跳表被预填了：{cf._last_heartbeat} —— 缺信息不得伪造为已知")

    def test_unknown_node_is_not_fabricated(self):
        """运行期首次问到的节点：返回 UNKNOWN，且**不写入**伪造时间戳"""
        cf = _engine()
        assert cf.check_primary_health('node_x') == PrimaryStatus.UNKNOWN
        assert 'node_x' not in cf._last_heartbeat, (
            "查询不得顺手写入时间戳（那会把「没消息」变成「刚收到」）")


class TestNoSpuriousFailover:
    def test_normal_round_does_not_trigger_failover(self):
        """正常轮（未收到心跳、状态 UNKNOWN）不得产生 failover 记录"""
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
    def test_reset_clears_heartbeat_table(self):
        """重置后心跳表清空 ⇒ UNKNOWN，不退回到「一律超时」的旧行为"""
        cf = _engine()
        cf.record_heartbeat('node_0')
        cf.reset_failover_state()
        assert cf._last_heartbeat == {}
        assert cf.check_primary_health('node_0') == PrimaryStatus.UNKNOWN

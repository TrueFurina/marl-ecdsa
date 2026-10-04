"""
action_recorder 更多边界测试（RalphLoop 原子任务 CN）
覆盖：flush_pending 过滤、pending_to_transaction 转换、统计、生命周期
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from marl.integration.action_recorder import ActionRecorder

logging.basicConfig(level=logging.CRITICAL)


def _pkg(verified=True, agent_id="a0"):
    pkg = {
        'signature_hex': '0x' + 'ab' * 32,
        'message_hex': '0x' + 'cd' * 16,
        'r': 12345,
        's': 67890,
    }
    if verified is not None:
        pkg['verified'] = verified
    return pkg


def _record(ar, agent="a0", verified=True, has_sig=True):
    ar.record_action(agent, 1, [0.1], 1.0, 1000, 1,
                     _pkg(verified=verified) if has_sig else None)


class TestFlushPending:
    def test_flush_no_bc_noop(self):
        """无 bc_node → flush 不崩溃、不计数"""
        ar = ActionRecorder(n_agents=3)
        _record(ar)
        ar.flush_pending()
        assert ar._tx_count == 0

    def test_flush_with_bc_adds_txs(self):
        """有 bc_node → flush 添加交易"""
        class _BC:
            def __init__(self):
                self.txs = []
            def add_transaction(self, tx):
                self.txs.append(tx)
        bc = _BC()
        ar = ActionRecorder(bc_node=bc, n_agents=3)
        _record(ar)
        ar.flush_pending()
        assert len(bc.txs) == 1
        assert ar._tx_count == 1
        assert len(ar._pending_actions) == 0  # 缓冲已清空

    def test_flush_filters_unverified(self):
        """flush 过滤 verified=False（仅可信行为上链）"""
        class _BC:
            def __init__(self):
                self.txs = []
            def add_transaction(self, tx):
                self.txs.append(tx)
        bc = _BC()
        ar = ActionRecorder(bc_node=bc, n_agents=3)
        _record(ar, "a0", verified=True)
        _record(ar, "a1", verified=False)  # 被过滤
        _record(ar, "a2", verified=None, has_sig=True)  # 无 verified 字段 → 可信
        ar.flush_pending()
        assert len(bc.txs) == 2  # a0 + a2，a1 被过滤


class TestPendingToTransaction:
    def test_conversion_fields(self):
        """pending → Transaction 字段映射"""
        ar = ActionRecorder(n_agents=3)
        pending = {
            'agent_id': 'a0', 'step': 5, 'action': [0.5],
            'action_hash': 'hash123', 'env_reward': 1.0,
            'timestamp': 1000, 'nonce': 3, 'signature_hex': '0x' + 'ab' * 32,
            'message_hex': '00', 'r': 1, 's': 2, 'verified': True,
        }
        tx = ar.pending_to_transaction(pending)
        assert tx is not None
        assert tx.agent_id == 'a0'
        assert tx.action_hash == 'hash123'
        assert tx.tx_id == tx.compute_hash()  # tx_id 由哈希派生

    def test_conversion_missing_required_returns_none(self):
        """缺必填字段（timestamp）→ KeyError 被捕获返回 None（降级契约）"""
        ar = ActionRecorder(n_agents=3)
        pending = {'agent_id': 'a0', 'action_hash': 'h1'}  # 缺 timestamp
        tx = ar.pending_to_transaction(pending)
        assert tx is None  # 构造失败降级

    def test_conversion_missing_optional_defaults(self):
        """缺可选字段（nonce/signature_hex）→ 默认值（不崩溃）"""
        ar = ActionRecorder(n_agents=3)
        pending = {
            'agent_id': 'a0', 'action_hash': 'h1', 'timestamp': 1000,
        }
        tx = ar.pending_to_transaction(pending)
        assert tx is not None
        assert tx.nonce == 0  # 默认
        assert tx.signature_hex == ''  # 默认

    def test_conversion_exception_returns_none(self):
        """构造异常 → None（降级）"""
        ar = ActionRecorder(n_agents=3)
        tx = ar.pending_to_transaction({})  # 缺 agent_id → KeyError → None
        assert tx is None


class TestStatsLifecycle:
    def test_get_stats_structure(self):
        """get_stats 含 pending_actions/tx_count"""
        ar = ActionRecorder(n_agents=3)
        _record(ar)
        stats = ar.get_stats()
        assert 'pending_actions' in stats
        assert 'tx_count' in stats
        assert stats['pending_actions'] == 1

    def test_batch_then_flush_lifecycle(self):
        """batch_upload + flush 完整生命周期"""
        class _BC:
            def __init__(self):
                self.txs = []
            def add_transaction(self, tx):
                self.txs.append(tx)
        bc = _BC()
        ar = ActionRecorder(bc_node=bc, n_agents=3)
        _record(ar, "a0")
        _record(ar, "a1")
        ar.batch_upload()  # 2 条上链
        _record(ar, "a2")  # 新行为
        ar.flush_pending()  # 1 条上链
        assert len(bc.txs) == 3
        assert ar._tx_count == 3
        assert len(ar._pending_actions) == 0

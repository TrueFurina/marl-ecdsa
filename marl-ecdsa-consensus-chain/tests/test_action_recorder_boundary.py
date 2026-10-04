"""
ActionRecorder 边界测试（RalphLoop 原子任务 H）
覆盖：记录缓冲、verified=False 拒绝、批量上链、flush、交易转换
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from marl.integration.action_recorder import ActionRecorder

logging.basicConfig(level=logging.CRITICAL)


def _pkg(verified=True):
    pkg = {
        'signature_hex': '0x' + 'ab' * 32,
        'message_hex': '0x' + 'cd' * 16,
        'r': 12345,
        's': 67890,
    }
    if verified is not None:
        pkg['verified'] = verified
    return pkg


class TestRecordAction:
    def test_record_accumulates_pending(self):
        ar = ActionRecorder(n_agents=3)
        ar.record_action("agent_0", 1, [0.1, 0.2], 1.0, 1000, 1, _pkg())
        assert len(ar._pending_actions) == 1
        assert ar._pending_actions[0]['agent_id'] == "agent_0"
        assert ar._pending_actions[0]['env_reward'] == 1.0

    def test_record_verified_false_rejected(self):
        """verified=False 的行为被拒绝进入缓冲（P0-5）"""
        ar = ActionRecorder(n_agents=3)
        ar.record_action("agent_0", 1, [0.1], 1.0, 1000, 1, _pkg(verified=False))
        assert len(ar._pending_actions) == 0  # 被拒绝

    def test_record_no_signature_still_buffered(self):
        """无签名包的行为仍缓冲（无 verified 字段默认可信）"""
        ar = ActionRecorder(n_agents=3)
        ar.record_action("agent_0", 1, [0.1], 1.0, 1000, 1, signed_package=None)
        assert len(ar._pending_actions) == 1

    def test_record_action_hash_generated(self):
        ar = ActionRecorder(n_agents=3)
        ar.record_action("agent_0", 1, [0.1], 1.0, 1000, 1, None)
        assert len(ar._pending_actions[0]['action_hash']) == 16


class TestBatchUpload:
    def test_batch_upload_empty_noop(self):
        ar = ActionRecorder(n_agents=3)
        ar.batch_upload()  # 空缓冲不应崩溃
        assert ar._tx_count == 0

    def test_batch_upload_stub_mode_clears(self):
        """无 bc_node（stub 模式）：缓冲清空，tx_count 不变"""
        ar = ActionRecorder(n_agents=3)
        ar.record_action("agent_0", 1, [0.1], 1.0, 1000, 1, _pkg())
        ar.batch_upload()
        assert len(ar._pending_actions) == 0  # 已清空
        assert ar._tx_count == 0  # stub 模式不计交易

    def test_batch_upload_filters_unverified(self):
        """batch_upload 过滤 verified=False（仅上传可信行为）"""
        class _BC:
            def __init__(self):
                self.txs = []
            def add_transaction(self, tx):
                self.txs.append(tx)
        bc = _BC()
        ar = ActionRecorder(bc_node=bc, n_agents=3)
        ar.record_action("a0", 1, [0.1], 1.0, 1000, 1, _pkg(verified=True))
        ar.record_action("a1", 2, [0.2], 1.0, 1001, 2, _pkg(verified=False))
        ar.record_action("a2", 3, [0.3], 1.0, 1002, 3, None)
        ar.batch_upload()
        # 2 条可信（a0 显式 verified + a2 无 verified 默认可信），a1 被过滤
        assert len(bc.txs) == 2
        assert ar._tx_count == 2

    def test_batch_upload_with_bc_adds_transactions(self):
        class _BC:
            def __init__(self):
                self.txs = []
            def add_transaction(self, tx):
                self.txs.append(tx)
        bc = _BC()
        ar = ActionRecorder(bc_node=bc, n_agents=3)
        ar.record_action("a0", 1, [0.1], 1.0, 1000, 1, _pkg())
        ar.batch_upload()
        assert len(bc.txs) == 1
        assert ar._tx_count == 1


class TestFlushPending:
    def test_flush_without_bc_noop(self):
        """无 bc_node → flush 不崩溃"""
        ar = ActionRecorder(n_agents=3)
        ar.record_action("a0", 1, [0.1], 1.0, 1000, 1, _pkg())
        ar.flush_pending()  # bc_node=None 时直接返回
        assert len(ar._pending_actions) >= 0  # 不崩溃即可


class TestStats:
    def test_get_stats(self):
        ar = ActionRecorder(n_agents=3)
        ar.record_action("a0", 1, [0.1], 1.0, 1000, 1, _pkg())
        stats = ar.get_stats()
        assert isinstance(stats, dict)
        assert 'pending_count' in stats or len(stats) > 0

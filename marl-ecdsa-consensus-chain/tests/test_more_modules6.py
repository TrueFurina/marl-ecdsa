"""
更多模块剩余边界测试（RalphLoop 原子任务 DF）
覆盖：signing_service/action_recorder 统计与生命周期组合（此前未单点覆盖）
通过标准：新增 ≥6 项测试全过
"""
import logging
import shutil
import tempfile
import time

import pytest

from marl.integration.signing_service import SigningService
from marl.integration.action_recorder import ActionRecorder
from blockchain.crypto.key_manager import KeyManager
from blockchain.crypto.security_guard import SecurityGuard

logging.basicConfig(level=logging.CRITICAL)


@pytest.fixture
def keyed():
    key_dir = tempfile.mkdtemp(prefix="test_sig_df_")
    km = KeyManager(key_dir=key_dir)
    guard = SecurityGuard()
    for i in range(3):
        km.generate_or_load(f"agent_{i}")
    svc = SigningService(key_manager=km, security_guard=guard, n_agents=3)
    yield svc, km
    shutil.rmtree(key_dir, ignore_errors=True)


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


class TestSigningStats:
    def test_stats_after_sign_verify(self, keyed):
        """签名+校验后统计增长"""
        svc, _ = keyed
        svc.sign_and_verify("agent_0", [0.1], 1, int(time.time() * 1000))
        stats = svc.get_stats()
        assert stats['ecdsa_sign_count'] == 1
        assert stats['security_pass_count'] == 1

    def test_stats_after_replay_blocked(self, keyed):
        """重放被拦截 → fail 计数"""
        svc, _ = keyed
        ts = int(time.time() * 1000)
        svc.sign_and_verify("agent_0", [0.1], 1, ts)
        svc.sign_and_verify("agent_0", [0.2], 1, ts)  # 重复 nonce
        stats = svc.get_stats()
        assert stats['security_fail_count'] == 1

    def test_stats_reset_preserves_counters(self, keyed):
        """reset_nonce_state 不影响统计计数"""
        svc, _ = keyed
        svc.sign_and_verify("agent_0", [0.1], 1, int(time.time() * 1000))
        svc.reset_nonce_state()
        assert svc.get_stats()['ecdsa_sign_count'] == 1  # 计数保留


class TestRecorderStats:
    def test_stats_pending_and_tx(self):
        """记录后 pending 计数"""
        ar = ActionRecorder(n_agents=3)
        ar.record_action("a0", 1, [0.1], 1.0, 1000, 1, _pkg())
        stats = ar.get_stats()
        assert stats['pending_actions'] == 1
        assert stats['tx_count'] == 0

    def test_stats_after_batch(self):
        """批量上链后 tx_count 增长"""
        class _BC:
            def __init__(self):
                self.txs = []
            def add_transaction(self, tx):
                self.txs.append(tx)
        bc = _BC()
        ar = ActionRecorder(bc_node=bc, n_agents=3)
        ar.record_action("a0", 1, [0.1], 1.0, 1000, 1, _pkg())
        ar.batch_upload()
        stats = ar.get_stats()
        assert stats['pending_actions'] == 0  # 已清空
        assert stats['tx_count'] == 1

    def test_recorder_rejects_unverified(self):
        """verified=False 记录被拒（pending 不增）"""
        ar = ActionRecorder(n_agents=3)
        ar.record_action("a0", 1, [0.1], 1.0, 1000, 1, _pkg(verified=False))
        assert len(ar._pending_actions) == 0


class TestLifecycleCombo:
    def test_batch_flush_cycle(self):
        """batch + flush 完整生命周期统计"""
        class _BC:
            def __init__(self):
                self.txs = []
            def add_transaction(self, tx):
                self.txs.append(tx)
        bc = _BC()
        ar = ActionRecorder(bc_node=bc, n_agents=3)
        ar.record_action("a0", 1, [0.1], 1.0, 1000, 1, _pkg())
        ar.batch_upload()
        ar.record_action("a1", 2, [0.2], 1.0, 1001, 2, _pkg())
        ar.flush_pending()
        assert ar.get_stats()['tx_count'] == 2
        assert len(bc.txs) == 2

    def test_signing_then_recorder_integration(self, keyed):
        """签名→记录→上链 集成链路"""
        svc, _ = keyed
        pkg = svc.sign_and_verify("agent_0", [0.1], 1, int(time.time() * 1000))
        assert pkg is not None
        assert pkg.get('verified') is True
        ar = ActionRecorder(n_agents=3)
        ar.record_action("agent_0", 1, [0.1], 1.0, 1000, 1, pkg)
        assert len(ar._pending_actions) == 1  # 可信签名包被记录

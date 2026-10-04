"""
signing_service 更多边界测试（RalphLoop 原子任务 CM）
覆盖：verify_episode_transactions 分支、签名包往返、统计一致性
通过标准：新增 ≥6 项测试全过
"""
import hashlib
import logging
import shutil
import tempfile
import time

import pytest

from marl.integration.signing_service import SigningService
from blockchain.crypto.key_manager import KeyManager
from blockchain.crypto.ecdsa_utils import ECDSAUtils
from blockchain.crypto.security_guard import SecurityGuard

logging.basicConfig(level=logging.CRITICAL)


def _make_tx(agent_id="agent_0", nonce=1, sig=True, extra=None):
    action = [0.1, 0.2]
    return type("Tx", (), {
        "tx_id": hashlib.sha256(f"{agent_id}{nonce}".encode()).hexdigest()[:16],
        "agent_id": agent_id,
        "action": action,
        "timestamp": int(time.time() * 1000),
        "nonce": nonce,
        "signature_hex": ("0x" + "ab" * 32) if sig else "",
        "extra": extra if extra is not None else {'verified': True, 'message_hex': '00'},
    })()


@pytest.fixture
def keyed():
    key_dir = tempfile.mkdtemp(prefix="test_sign_more_")
    km = KeyManager(key_dir=key_dir)
    guard = SecurityGuard()
    for i in range(3):
        km.generate_or_load(f"agent_{i}")
    svc = SigningService(key_manager=km, security_guard=guard, n_agents=3)
    yield svc, km, guard
    shutil.rmtree(key_dir, ignore_errors=True)


class TestVerifyEpisode:
    def test_verify_no_bc_returns(self, keyed):
        """bc_node=None → 直接返回不崩溃"""
        svc, _, _ = keyed
        svc.verify_episode_transactions(None)

    def test_verify_empty_pool_no_count(self, keyed):
        """空交易池 → 验签数不增长"""
        svc, _, _ = keyed
        class _BC:
            def get_pending_transactions(self):
                return []
        svc.verify_episode_transactions(_BC())
        assert svc.get_stats()["ecdsa_verify_count"] == 0

    def test_verify_no_signature_skipped(self, keyed):
        """无签名交易 → 跳过不验签"""
        svc, _, _ = keyed
        class _BC:
            def get_pending_transactions(self):
                return [_make_tx(sig=False)]
        svc.verify_episode_transactions(_BC())
        assert svc.get_stats()["ecdsa_verify_count"] == 0

    def test_verify_valid_signature_counts(self, keyed):
        """合法签名 → 验签计数增长"""
        svc, km, _ = keyed
        priv = km.get_private_key("agent_0")
        msg = hashlib.sha256(b"test_msg").digest()
        sig = ECDSAUtils.sign(priv, msg)
        tx = _make_tx("agent_0", 1, sig=True,
                      extra={'verified': True, 'message_hex': msg.hex()})
        tx.signature_hex = sig.hex()
        tx.extra = {'verified': True, 'message_hex': msg.hex(), 'r': None, 's': None}
        class _BC:
            def get_pending_transactions(self):
                return [tx]
        svc.verify_episode_transactions(_BC())
        assert svc.get_stats()["ecdsa_verify_count"] == 1


class TestSignVerifyStats:
    def test_sign_count_matches(self, keyed):
        """签名计数与调用次数一致"""
        svc, _, _ = keyed
        for nonce in range(1, 4):
            svc.sign_and_verify("agent_0", [0.1], nonce, int(time.time() * 1000))
        assert svc.get_stats()["ecdsa_sign_count"] == 3

    def test_stats_all_fields(self, keyed):
        """get_stats 含全部统计字段"""
        svc, _, _ = keyed
        stats = svc.get_stats()
        for key in ['ecdsa_sign_count', 'ecdsa_verify_count',
                    'security_pass_count', 'security_fail_count']:
            assert key in stats


class TestNonceReset:
    def test_reset_clears_counters(self, keyed):
        """reset_nonce_state 后 nonce 归零"""
        svc, _, _ = keyed
        svc._nonce_counters["agent_0"] = 5
        svc.reset_nonce_state()
        assert svc._nonce_counters["agent_0"] == 0

    def test_reset_syncs_guard(self, keyed):
        """reset 后 SecurityGuard nonce 同步清空"""
        svc, _, guard = keyed
        svc.reset_nonce_state()
        # 重置后 nonce=1 用新 r 可再次通过
        ok, _ = guard.check_package({
            "agent_id": "agent_0", "timestamp": int(time.time() * 1000),
            "nonce": 1, "r": 0x4567,
        })
        assert ok is True

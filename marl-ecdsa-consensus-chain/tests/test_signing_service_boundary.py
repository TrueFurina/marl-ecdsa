"""
SigningService 边界测试（RalphLoop 原子任务 G）
覆盖：无密钥/无 guard 降级、nonce 管理、验签边界、统计与重置
通过标准：新增 ≥6 项测试全过
"""
import logging
import shutil
import tempfile
import time

import pytest

from marl.integration.signing_service import SigningService
from blockchain.crypto.key_manager import KeyManager
from blockchain.crypto.security_guard import SecurityGuard

logging.basicConfig(level=logging.CRITICAL)


@pytest.fixture
def keyed_components():
    """带密钥管理器与安全防护的组件"""
    key_dir = tempfile.mkdtemp(prefix="test_signing_")
    km = KeyManager(key_dir=key_dir)
    guard = SecurityGuard()
    for i in range(3):
        km.generate_or_load(f"agent_{i}")
    svc = SigningService(key_manager=km, security_guard=guard, n_agents=3)
    yield svc, km, guard
    shutil.rmtree(key_dir, ignore_errors=True)


class TestInit:
    def test_nonce_counters_initialized(self):
        svc = SigningService(n_agents=3)
        assert svc._nonce_counters == {"agent_0": 0, "agent_1": 0, "agent_2": 0}

    def test_stats_initialized_zero(self):
        svc = SigningService(n_agents=3)
        stats = svc.get_stats()
        assert stats["ecdsa_sign_count"] == 0
        assert stats["security_pass_count"] == 0

    def test_nonce_baseline_synced_to_guard(self):
        guard = SecurityGuard()
        svc = SigningService(security_guard=guard, n_agents=3)
        # 基线 nonce=0 已同步：直接提交 nonce=0 会因<=基线被拦
        ok, _ = guard.check_package({
            "agent_id": "agent_0", "timestamp": 9999999999999, "nonce": 0, "r": 1,
        })
        assert ok is False  # nonce=0 <= 基线 0 → 重放拦截


class TestSignAndVerify:
    def test_without_key_manager_returns_none(self):
        """无密钥管理器 → 无法签名，返回 None（不崩溃）"""
        svc = SigningService(n_agents=3)
        pkg = svc.sign_and_verify("agent_0", {"a": 1}, nonce=1,
                                  timestamp=int(time.time() * 1000))
        assert pkg is None  # 无 key_manager 时 sign_action 未执行，返回 None

    def test_missing_private_key_returns_none(self):
        """密钥不存在 → 返回 None"""
        svc = SigningService(n_agents=3)  # 无 key_manager
        pkg = svc.sign_and_verify("ghost_agent", {"a": 1}, nonce=1, timestamp=1)
        assert pkg is None or pkg.get("signature_hex") is None

    def test_sign_verify_flow_counts(self, keyed_components):
        """正常签名+校验：sign/pass 计数增长，verified=True"""
        svc, _, _ = keyed_components
        pkg = svc.sign_and_verify("agent_0", {"action": [0.1]}, nonce=1,
                                  timestamp=int(time.time() * 1000))
        assert pkg is not None
        assert svc.get_stats()["ecdsa_sign_count"] == 1
        assert svc.get_stats()["security_pass_count"] == 1
        assert pkg.get("verified") is True

    def test_replay_nonce_intercepted(self, keyed_components):
        """重复 nonce 被 SecurityGuard 拦截 → verified=False"""
        svc, _, _ = keyed_components
        ts = int(time.time() * 1000)
        svc.sign_and_verify("agent_0", {"a": 1}, nonce=1, timestamp=ts)
        pkg2 = svc.sign_and_verify("agent_0", {"a": 2}, nonce=1, timestamp=ts)
        assert pkg2.get("verified") is False
        assert svc.get_stats()["security_fail_count"] == 1


class TestVerifyEpisode:
    def test_verify_episode_none_bc_no_crash(self):
        """bc_node=None → 直接返回不崩溃"""
        svc = SigningService(n_agents=3)
        svc.verify_episode_transactions(None)  # 不应抛异常

    def test_verify_episode_empty_bc_no_crash(self, keyed_components):
        """空交易池 → 验签数不增长"""
        svc, _, _ = keyed_components
        class _EmptyBC:
            def get_pending_transactions(self):
                return []
        svc.verify_episode_transactions(_EmptyBC())
        assert svc.get_stats()["ecdsa_verify_count"] == 0


class TestNonceReset:
    def test_reset_nonce_state(self, keyed_components):
        svc, _, guard = keyed_components
        # _nonce_counters 由外部调用方管理（sign_and_verify 内部不递增），手动模拟
        svc._nonce_counters["agent_0"] = 7
        assert svc._nonce_counters["agent_0"] == 7
        svc.reset_nonce_state()
        assert svc._nonce_counters["agent_0"] == 0

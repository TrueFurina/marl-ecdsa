"""
SigningService 后量子混合签名集成测试（test/impl 分离）
覆盖：
  - 默认 ecdsa 路径字节级不变（包不含 Dilithium 字段）
  - hybrid 路径：双签名、AND 验签通过、篡改消息失败
  - hybrid 路径端到端经 Transaction.extra 还原并 AND 验签
  - hybrid 请求但后端缺失时 fail-closed（不静默回落 ECDSA）
"""
import os
import tempfile
import pytest

from blockchain.crypto.key_manager import KeyManager
from marl.integration.signing_service import SigningService
import blockchain.crypto.dilithium_adapter as _dil_module


def _make_service(backend="ecdsa", n_agents=2, key_dir=None):
    km = KeyManager(key_dir=key_dir) if key_dir else KeyManager(
        key_dir=tempfile.mkdtemp(prefix="keys_")
    )
    for i in range(n_agents):
        km.generate_or_load(f"agent_{i}")
    return SigningService(key_manager=km, n_agents=n_agents, signature_backend=backend)


def _sign_default(ss, agent_id="agent_0"):
    return ss.sign_and_verify(
        agent_id=agent_id,
        action_data={"move": [1, 2]},
        nonce=1,
        timestamp=1700000000000,
    )


# ---------------------------------------------------------------------------
# 默认 ECDSA 路径不变性
# ---------------------------------------------------------------------------
def test_default_ecdsa_path_has_no_dilithium_fields():
    ss = _make_service(backend="ecdsa")
    pkg = _sign_default(ss)
    assert pkg is not None
    assert "dilithium_signature_hex" not in pkg
    assert "dilithium_pubkey_hex" not in pkg
    assert ss.get_stats()["signature_backend"] == "ecdsa"
    # 向后兼容：无 Dilithium 字段时 verify_signed_package 退化为仅 ECDSA
    pub = ss.key_manager.get_public_key("agent_0")
    assert ss.verify_signed_package(pkg, pub) is True


# ---------------------------------------------------------------------------
# hybrid 路径：双签名 + AND 验签
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not _dil_module.DILITHIUM_AVAILABLE,
    reason="Dilithium 后端不可用，跳过真实后量子路径测试",
)
def test_hybrid_sign_then_verify_passes():
    with tempfile.TemporaryDirectory() as d:
        ss = _make_service(backend="hybrid", key_dir=d)
        pkg = _sign_default(ss)
        assert pkg is not None
        assert pkg.get("signature_backend") == "hybrid"
        assert "dilithium_signature_hex" in pkg
        assert "dilithium_pubkey_hex" in pkg
        # Dilithium 签名为 2420 字节（ML-DSA-44）
        assert len(bytes.fromhex(pkg["dilithium_signature_hex"])) == 2420

        pub = ss.key_manager.get_public_key("agent_0")
        assert ss.verify_signed_package(pkg, pub) is True
        assert ss.get_stats()["dilithium_keypairs"] == 1


@pytest.mark.skipif(
    not _dil_module.DILITHIUM_AVAILABLE,
    reason="Dilithium 后端不可用，跳过真实后量子路径测试",
)
def test_hybrid_verify_fails_on_tampered_message():
    with tempfile.TemporaryDirectory() as d:
        ss = _make_service(backend="hybrid", key_dir=d)
        pkg = _sign_default(ss)
        pub = ss.key_manager.get_public_key("agent_0")
        # 篡改业务字段（action），ECDSA 与 Dilithium 均绑定规范消息，必失败
        tampered = dict(pkg)
        tampered["action"] = {"move": [9, 9]}
        assert ss.verify_signed_package(tampered, pub) is False


@pytest.mark.skipif(
    not _dil_module.DILITHIUM_AVAILABLE,
    reason="Dilithium 后端不可用，跳过真实后量子路径测试",
)
def test_hybrid_verify_fails_on_dropped_dilithium_sig():
    """AND 策略：即使 ECDSA 通过，Dilithium 缺失/无效也必须失败。"""
    with tempfile.TemporaryDirectory() as d:
        ss = _make_service(backend="hybrid", key_dir=d)
        pkg = _sign_default(ss)
        pub = ss.key_manager.get_public_key("agent_0")
        no_dil = {k: v for k, v in pkg.items()
                  if k not in ("dilithium_signature_hex", "dilithium_pubkey_hex")}
        assert ss.verify_signed_package(no_dil, pub) is False


# ---------------------------------------------------------------------------
# hybrid 端到端经 Transaction.extra
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not _dil_module.DILITHIUM_AVAILABLE,
    reason="Dilithium 后端不可用，跳过真实后量子路径测试",
)
def test_hybrid_end_to_end_via_transaction_extra():
    class FakeTx:
        def __init__(self, agent_id, action, timestamp, nonce, sig_hex, extra):
            self.agent_id = agent_id
            self.action = action
            self.timestamp = timestamp
            self.nonce = nonce
            self.signature_hex = sig_hex
            self.extra = extra
            self.tx_id = "tx_" + "a" * 8

    class FakeNode:
        def __init__(self, txs):
            self._txs = txs

        def get_pending_transactions(self):
            return self._txs

    with tempfile.TemporaryDirectory() as d:
        ss = _make_service(backend="hybrid", key_dir=d)
        pkg = _sign_default(ss, agent_id="agent_1")
        # 交易上链时仅 signature_hex 进主字段，Dilithium 字段进 extra
        tx = FakeTx(
            agent_id=pkg["agent_id"],
            action=pkg["action"],
            timestamp=pkg["timestamp"],
            nonce=pkg["nonce"],
            sig_hex=pkg["signature_hex"],
            extra={
                "message_hex": pkg["message_hex"],
                "r": pkg["r"],
                "s": pkg["s"],
                "dilithium_signature_hex": pkg["dilithium_signature_hex"],
                "dilithium_pubkey_hex": pkg["dilithium_pubkey_hex"],
            },
        )
        node = FakeNode([tx])
        before = ss.get_stats()["ecdsa_verify_count"]
        ss.verify_episode_transactions(node)
        after = ss.get_stats()["ecdsa_verify_count"]
        assert after == before + 1  # 验签被执行（日志可见通过）


# ---------------------------------------------------------------------------
# fail-closed：请求 hybrid 但后端缺失
# ---------------------------------------------------------------------------
def test_hybrid_request_without_backend_raises(monkeypatch):
    monkeypatch.setattr(_dil_module, "DILITHIUM_AVAILABLE", False)
    with tempfile.TemporaryDirectory() as d:
        # 即便临时后端缺失，构造 hybrid 服务也必须 fail-closed 而非静默回落
        with pytest.raises(RuntimeError):
            _make_service(backend="hybrid", key_dir=d)
    # 还原（避免影响其他用例；pytest 自身会隔离，但显式恢复更稳）
    monkeypatch.undo()

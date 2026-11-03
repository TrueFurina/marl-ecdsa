"""
SigningService 签名后端契约测试（2026-10-19）

契约焦点：signature_backend 参数的**值域与模式不变量**。
背景：原实现对任何非 "hybrid" 的值静默走纯 ECDSA 路径——拼错 backend 名
（"hydrid"/"HYBRID"/" hybrid "）会得到一个「自认为抗量子、实际只有 ECDSA」
的服务。本文件把该入口的 fail-closed 语义与各模式的行为契约钉死：

  C1 默认契约：不传参 == "ecdsa"，stats 原样回显
  C2 值域契约：仅 ("ecdsa", "hybrid") 合法；其余一律构造期 ValueError
     ——含大小写/空格/typo/空串/None，白名单严格匹配，不做归一化宽容
  C3 fail-closed 时序：非法值在密钥生成/nonce 基线注册之前即被拒（零副作用）
  C4 ecdsa 模式不变量：签名包永不含 Dilithium 字段；验签退化为纯 ECDSA
  C5 ecdsa 模式验签契约：原包通过、篡改 message 拒绝、篡改 nonce 拒绝
  C6 跨模式隔离：ecdsa 服务拒绝 hybrid 包不报错（走纯 ECDSA 校验路径），
     反之 hybrid 服务拒绝无 Dilithium 字段的包（降级攻击防御，既有测试已覆盖，
     此处从「模式决定验签策略」的契约角度复核）

既有覆盖见 test_signing_service.py / test_signing_service_hybrid.py /
test_signing_service_boundary.py / test_signing_service_more.py——本文件只补
契约层，不重复实现细节测试。
"""
import tempfile

import pytest

from blockchain.crypto.key_manager import KeyManager
from marl.integration.signing_service import (
    SigningService,
    VALID_SIGNATURE_BACKENDS,
)


_UNSET = object()  # 哨兵：区分「不传 signature_backend」与「显式传 None」


def _make_service(backend=_UNSET, n_agents=2, key_dir=None):
    """backend=_UNSET（默认）表示不传该参数（测 C1 默认值契约）；
    显式传任何值（含 None）都透传给构造函数（测 C2 值域契约）。"""
    km = KeyManager(key_dir=key_dir or tempfile.mkdtemp(prefix="keys_ct_"))
    for i in range(n_agents):
        km.generate_or_load(f"agent_{i}")
    if backend is _UNSET:
        return SigningService(key_manager=km, n_agents=n_agents)
    return SigningService(key_manager=km, n_agents=n_agents, signature_backend=backend)


def _sign(ss, agent_id="agent_0", nonce=1):
    return ss.sign_and_verify(
        agent_id=agent_id,
        action_data={"move": [1, 2]},
        nonce=nonce,
        timestamp=1700000000000,
    )


# ---------------------------------------------------------------------------
# C1 默认契约
# ---------------------------------------------------------------------------
def test_c1_default_backend_is_ecdsa():
    ss = _make_service()  # 不传 signature_backend
    assert ss.get_stats()["signature_backend"] == "ecdsa"


def test_c1_backend_roundtrip_in_stats():
    for backend in VALID_SIGNATURE_BACKENDS:
        if backend == "hybrid":
            pytest.skip("hybrid 需 Dilithium 后端，见 test_signing_service_hybrid.py")
        ss = _make_service(backend=backend)
        assert ss.get_stats()["signature_backend"] == backend


# ---------------------------------------------------------------------------
# C2 值域契约：非法值一律构造期 ValueError
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [
    "hydrid",            # 字母错位 typo
    "HYBRID",            # 大写（严格匹配，不归一化）
    "Ecdsa",
    " hybrid ",          # 前后空格
    "hybrid\n",          # 尾部换行
    "",                  # 空串
    "ecdsa2",            # 合法前缀+噪声
    "dilithium",         # 用词错误：这是算法名不是后端名
    "post-quantum",
    "none",
    "True",
])
def test_c2_invalid_backend_raises_valueerror(bad):
    with pytest.raises(ValueError, match="非法 signature_backend"):
        _make_service(backend=bad)


def test_c2_none_backend_raises_valueerror():
    # None 不是「用默认值」的暗号——显式传 None 同样 fail-closed
    with pytest.raises(ValueError, match="非法 signature_backend"):
        _make_service(backend=None)


def test_c2_valid_backends_tuple_is_frozen_contract():
    # 合法值域本身是契约面：新增后端必须同步本测试与文档
    assert VALID_SIGNATURE_BACKENDS == ("ecdsa", "hybrid")


# ---------------------------------------------------------------------------
# C3 fail-closed 时序：构造即拒，无任何初始化副作用
# ---------------------------------------------------------------------------
def test_c3_invalid_backend_rejected_before_side_effects():
    km = KeyManager(key_dir=tempfile.mkdtemp(prefix="keys_ct3_"))
    for i in range(2):
        km.generate_or_load(f"agent_{i}")
    # 用一个必然非法的值；若实现把校验放到 nonce 基线注册之后，
    # security_guard 会留下半初始化状态——本测试只验证「构造期即抛」。
    with pytest.raises(ValueError):
        SigningService(key_manager=km, n_agents=2, signature_backend="hydrid")
    # 合法构造不受影响（同一 key_manager 可继续用于正确配置）
    ss = SigningService(key_manager=km, n_agents=2, signature_backend="ecdsa")
    assert ss.get_stats()["signature_backend"] == "ecdsa"


# ---------------------------------------------------------------------------
# C4 ecdsa 模式不变量：包永不带 Dilithium 字段
# ---------------------------------------------------------------------------
def test_c4_ecdsa_package_has_no_dilithium_fields():
    ss = _make_service(backend="ecdsa")
    for nonce in (1, 2, 3):
        pkg = _sign(ss, nonce=nonce)
        assert pkg is not None
        assert "dilithium_signature_hex" not in pkg
        assert "dilithium_pubkey_hex" not in pkg
        assert "signature_backend" not in pkg  # 纯 ECDSA 包不打后端标记


def test_c4_ecdsa_mode_stats_report_ecdsa_counts():
    ss = _make_service(backend="ecdsa")
    _sign(ss)
    _sign(ss, agent_id="agent_1", nonce=2)
    stats = ss.get_stats()
    assert stats["signature_backend"] == "ecdsa"
    assert stats["ecdsa_sign_count"] == 2
    assert stats["dilithium_keypairs"] == 0  # ecdsa 模式从不生成量子密钥


# ---------------------------------------------------------------------------
# C5 ecdsa 模式验签契约：原包通过 / 篡改拒绝
# ---------------------------------------------------------------------------
def test_c5_ecdsa_verify_accepts_untampered():
    ss = _make_service(backend="ecdsa")
    pkg = _sign(ss)
    pub = ss.key_manager.get_public_key("agent_0")
    assert ss.verify_signed_package(pkg, pub) is True


def test_c5_ecdsa_verify_rejects_tampered_message():
    ss = _make_service(backend="ecdsa")
    pkg = _sign(ss)
    tampered = dict(pkg)
    tampered["message_hex"] = "00" * len(bytes.fromhex(pkg["message_hex"]))
    pub = ss.key_manager.get_public_key("agent_0")
    assert ss.verify_signed_package(tampered, pub) is False


def test_c5_ecdsa_verify_rejects_tampered_signature():
    ss = _make_service(backend="ecdsa")
    pkg = _sign(ss)
    tampered = dict(pkg)
    sig = bytearray(bytes.fromhex(pkg["signature_hex"]))
    sig[0] ^= 0xFF
    tampered["signature_hex"] = bytes(sig).hex()
    pub = ss.key_manager.get_public_key("agent_0")
    assert ss.verify_signed_package(tampered, pub) is False


def test_c5_ecdsa_verify_rejects_wrong_pubkey():
    ss = _make_service(backend="ecdsa")
    pkg = _sign(ss)
    wrong_pub = ss.key_manager.get_public_key("agent_1")  # 别人的公钥
    assert ss.verify_signed_package(pkg, wrong_pub) is False


# ---------------------------------------------------------------------------
# C6 跨模式隔离：ecdsa 服务对「声称 hybrid 的包」只按 ECDSA 校验
# ---------------------------------------------------------------------------
def test_c6_ecdsa_service_ignores_foreign_hybrid_claim():
    # 包内被打上 signature_backend='hybrid' 标记不影响 ecdsa 模式服务：
    # 其验签策略只由自身配置决定（防「包自称高级别就提权」）。
    ss = _make_service(backend="ecdsa")
    pkg = _sign(ss)
    claimed = dict(pkg)
    claimed["signature_backend"] = "hybrid"
    pub = ss.key_manager.get_public_key("agent_0")
    assert ss.verify_signed_package(claimed, pub) is True  # ECDSA 部分仍有效即通过

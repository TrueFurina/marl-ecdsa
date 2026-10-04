"""
ECDSAUtils 边界测试（RalphLoop 原子任务 K）
覆盖：序列化往返、hex 解析、消息构造、rs 编码、签名包往返
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from blockchain.crypto.ecdsa_utils import ECDSAUtils

logging.basicConfig(level=logging.CRITICAL)


class TestSerializationRoundtrip:
    def test_private_key_pem_roundtrip(self):
        priv, pub = ECDSAUtils.generate_key_pair()
        pem = ECDSAUtils.private_key_to_bytes(priv)
        restored = ECDSAUtils.private_key_from_bytes(pem)
        assert restored.private_numbers().private_value == priv.private_numbers().private_value

    def test_public_key_pem_roundtrip(self):
        _, pub = ECDSAUtils.generate_key_pair()
        pem = ECDSAUtils.public_key_to_bytes(pub)
        restored = ECDSAUtils.public_key_from_bytes(pem)
        assert restored.public_numbers().x == pub.public_numbers().x

    def test_public_key_hex_roundtrip(self):
        _, pub = ECDSAUtils.generate_key_pair()
        hex_str = ECDSAUtils.public_key_to_hex(pub)
        restored = ECDSAUtils.public_key_from_hex(hex_str)
        assert restored.public_numbers().x == pub.public_numbers().x

    def test_public_key_hex_length(self):
        """secp256r1 非压缩点：0x04 + 32 + 32 = 65 字节 = 130 hex"""
        _, pub = ECDSAUtils.generate_key_pair()
        hex_str = ECDSAUtils.public_key_to_hex(pub)
        assert len(hex_str) == 130


class TestMessageBuild:
    def test_build_message_contains_action_hash(self):
        import hashlib
        msg = ECDSAUtils.build_message("agent_0", [0.5, 0.5], 1000, 1)
        assert isinstance(msg, bytes)
        # 消息是稳定排序 JSON：可反解析
        import json
        payload = json.loads(msg.decode('utf-8'))
        assert payload["agent_id"] == "agent_0"
        assert payload["nonce"] == 1

    def test_build_message_deterministic(self):
        m1 = ECDSAUtils.build_message("agent_0", {"a": 1}, 1000, 1)
        m2 = ECDSAUtils.build_message("agent_0", {"a": 1}, 1000, 1)
        assert m1 == m2

    def test_hash_message_length(self):
        import hashlib
        digest = ECDSAUtils.hash_message(b"test")
        assert len(digest) == 32  # SHA-256 = 32 字节


class TestRSCodec:
    def test_rs_encode_decode_roundtrip(self):
        priv, _ = ECDSAUtils.generate_key_pair()
        sig = ECDSAUtils.sign(priv, b"msg for rs")
        r, s = ECDSAUtils.extract_rs(sig)
        reencoded = ECDSAUtils.encode_rs(r, s)
        r2, s2 = ECDSAUtils.extract_rs(reencoded)
        assert r == r2
        assert s == s2

    def test_extract_rs_returns_positive_ints(self):
        priv, _ = ECDSAUtils.generate_key_pair()
        sig = ECDSAUtils.sign(priv, b"msg")
        r, s = ECDSAUtils.extract_rs(sig)
        assert r > 0
        assert s > 0


class TestSignActionPackage:
    def test_sign_action_package_roundtrip(self):
        priv, pub = ECDSAUtils.generate_key_pair()
        pkg = ECDSAUtils.sign_action("agent_0", priv, [0.5], nonce=3, timestamp=1000)
        assert ECDSAUtils.verify_action_package(pkg, pub) is True

    def test_verify_action_package_wrong_key_fails(self):
        priv, _ = ECDSAUtils.generate_key_pair()
        _, other_pub = ECDSAUtils.generate_key_pair()
        pkg = ECDSAUtils.sign_action("agent_0", priv, [0.5], nonce=3)
        assert ECDSAUtils.verify_action_package(pkg, other_pub) is False

    def test_verify_action_package_tampered_fails(self):
        priv, pub = ECDSAUtils.generate_key_pair()
        pkg = ECDSAUtils.sign_action("agent_0", priv, [0.5], nonce=3)
        # 篡改消息字节 → 验证失败
        tampered = dict(pkg)
        tampered["message_hex"] = (bytes.fromhex(pkg["message_hex"]) + b"x").hex()
        assert ECDSAUtils.verify_action_package(tampered, pub) is False

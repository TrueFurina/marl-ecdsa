"""
ECDSA 密码学模块测试
测试 secp256r1 (P-256) 签名/验签的完整流程
"""
import pytest
import hashlib
import json


@pytest.mark.crypto
class TestECDSAKeyGeneration:
    """密钥对生成测试"""

    def test_generate_key_pair_success(self, ecdsa_utils):
        """验证密钥对生成成功"""
        private_key, public_key = ecdsa_utils.generate_key_pair()
        assert private_key is not None
        assert public_key is not None
        assert private_key.key_size == 256  # P-256

    def test_generated_keys_are_unique(self, ecdsa_utils):
        """每次生成的密钥对应不同"""
        pk1, pub1 = ecdsa_utils.generate_key_pair()
        pk2, pub2 = ecdsa_utils.generate_key_pair()
        # 公钥的序列化表示应不同
        assert ecdsa_utils.public_key_to_bytes(pub1) != ecdsa_utils.public_key_to_bytes(pub2)

    def test_key_pair_matching(self, ecdsa_utils):
        """公钥与私钥匹配"""
        private_key, public_key = ecdsa_utils.generate_key_pair()
        # 从私钥导出的公钥应与生成的公钥一致
        derived_public = private_key.public_key()
        assert ecdsa_utils.public_key_to_bytes(public_key) == ecdsa_utils.public_key_to_bytes(derived_public)


@pytest.mark.crypto
class TestECDSASignAndVerify:
    """签名与验签测试"""

    def test_sign_and_verify_success(self, ecdsa_utils, key_pair):
        """正常消息签名后验签通过"""
        private_key, public_key = key_pair
        message = b"MARL-ECDSA Consensus Chain Test Message"
        msg_hash = hashlib.sha256(message).digest()

        signature = ecdsa_utils.sign(private_key, msg_hash)
        assert signature is not None

        result = ecdsa_utils.verify(public_key, msg_hash, signature)
        assert result is True

    def test_verify_tampered_message_fails(self, ecdsa_utils, key_pair):
        """篡改消息后验签失败"""
        private_key, public_key = key_pair
        msg1 = hashlib.sha256(b"original message").digest()
        msg2 = hashlib.sha256(b"tampered message").digest()

        signature = ecdsa_utils.sign(private_key, msg1)
        result = ecdsa_utils.verify(public_key, msg2, signature)
        assert result is False

    def test_verify_wrong_key_fails(self, ecdsa_utils):
        """用错误公钥验签失败"""
        private_key, _ = ecdsa_utils.generate_key_pair()
        _, wrong_public = ecdsa_utils.generate_key_pair()

        msg_hash = hashlib.sha256(b"test").digest()
        signature = ecdsa_utils.sign(private_key, msg_hash)
        result = ecdsa_utils.verify(wrong_public, msg_hash, signature)
        assert result is False

    def test_multiple_signatures_different(self, ecdsa_utils, key_pair):
        """同一私钥对不同消息的签名应不同"""
        private_key, public_key = key_pair
        msg1 = hashlib.sha256(b"message one").digest()
        msg2 = hashlib.sha256(b"message two").digest()

        sig1 = ecdsa_utils.sign(private_key, msg1)
        sig2 = ecdsa_utils.sign(private_key, msg2)

        # 签名应不同（相同消息hash不同k值可能产生相同r但通常不同）
        assert sig1 != sig2

    def test_sign_with_json_data(self, ecdsa_utils, key_pair):
        """JSON 数据签名/验签（模拟真实场景）"""
        private_key, public_key = key_pair
        data = {
            "agent_id": "agent_0",
            "action": 3,
            "position": [0.72, 0.31],
            "nonce": 42,
            "timestamp": 1719480000000
        }
        msg = json.dumps(data, sort_keys=True).encode()
        msg_hash = hashlib.sha256(msg).digest()

        signature = ecdsa_utils.sign(private_key, msg_hash)
        assert ecdsa_utils.verify(public_key, msg_hash, signature) is True


@pytest.mark.crypto
class TestECDSAKeySerialization:
    """密钥序列化测试"""

    def test_serialize_and_deserialize_private_key(self, ecdsa_utils):
        """私钥序列化往返一致"""
        private_key, _ = ecdsa_utils.generate_key_pair()
        pem_data = ecdsa_utils.private_key_to_bytes(private_key)
        assert isinstance(pem_data, bytes)
        assert pem_data.startswith(b'-----BEGIN PRIVATE KEY-----')

        restored = ecdsa_utils.private_key_from_bytes(pem_data)
        assert restored is not None
        assert ecdsa_utils.private_key_to_bytes(private_key) == ecdsa_utils.private_key_to_bytes(restored)

    def test_serialize_and_deserialize_public_key(self, ecdsa_utils):
        """公钥序列化往返一致"""
        _, public_key = ecdsa_utils.generate_key_pair()
        pem_data = ecdsa_utils.public_key_to_bytes(public_key)
        assert isinstance(pem_data, bytes)

        restored = ecdsa_utils.public_key_from_bytes(pem_data)
        assert restored is not None
        assert ecdsa_utils.public_key_to_bytes(public_key) == ecdsa_utils.public_key_to_bytes(restored)


@pytest.mark.crypto
class TestECDSASignatureDecoding:
    """签名解码测试"""

    def test_decode_signature_extracts_r_s(self, ecdsa_utils, key_pair):
        """从 DER 签名中提取 r, s 值"""
        private_key, _ = key_pair
        msg_hash = hashlib.sha256(b"test decode").digest()

        signature = ecdsa_utils.sign(private_key, msg_hash)
        r, s = ecdsa_utils.extract_rs(signature)

        assert isinstance(r, int)
        assert isinstance(s, int)
        assert r > 0
        assert s > 0

    def test_decode_signature_deterministic(self, ecdsa_utils, key_pair):
        """同一签名解码两次结果一致"""
        private_key, _ = key_pair
        msg_hash = hashlib.sha256(b"test deterministic").digest()

        signature = ecdsa_utils.sign(private_key, msg_hash)
        r1, s1 = ecdsa_utils.extract_rs(signature)
        r2, s2 = ecdsa_utils.extract_rs(signature)

        assert r1 == r2
        assert s1 == s2

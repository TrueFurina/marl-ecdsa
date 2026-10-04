"""
更多模块剩余边界测试（RalphLoop 原子任务 CX）
覆盖：cw_pbft 共识路径、ecdsa_utils 消息构建/签名包（此前未单点覆盖）
通过标准：新增 ≥6 项测试全过
"""
import hashlib
import logging
import shutil
import tempfile

import pytest

from blockchain.consensus.cw_pbft import CWPBFTConsensus
from blockchain.crypto.ecdsa_utils import ECDSAUtils
from blockchain.crypto.key_manager import KeyManager

logging.basicConfig(level=logging.CRITICAL)

NODES = ['node_0', 'node_1', 'node_2']


@pytest.fixture
def pbft():
    return CWPBFTConsensus('node_0', NODES)


class TestCWPBFTPaths:
    def test_fast_consensus(self, pbft):
        """快速共识：直接成功"""
        ok = pbft.fast_consensus('hash_fast', 'node_0')
        assert ok is True
        stats = pbft.get_consensus_stats()
        assert stats['consensus_success_rate'] == 1.0

    def test_simulated_consensus(self, pbft):
        """模拟共识：三阶段达成"""
        ok = pbft.simulated_consensus('hash_sim', 'node_1')
        assert ok is True

    def test_start_consensus_returns_vote(self, pbft):
        """start_consensus 返回 pre_prepare 投票（主节点发起阶段）"""
        vote = pbft.start_consensus('hash_vote')
        assert vote is not None
        assert vote.phase == 'pre_prepare'

    def test_fast_consensus_resets_state(self, pbft):
        """快速共识后状态可再次共识（IDLE 复位）"""
        pbft.fast_consensus('h1', 'node_0')
        ok = pbft.fast_consensus('h2', 'node_1')  # 连续两轮
        assert ok is True


class TestECDSAMessage:
    def test_build_message_deterministic(self):
        """消息构建确定性"""
        m1 = ECDSAUtils.build_message("agent_0", [0.5], 1000, 1)
        m2 = ECDSAUtils.build_message("agent_0", [0.5], 1000, 1)
        assert m1 == m2

    def test_build_message_differs_by_nonce(self):
        """nonce 不同 → 消息不同"""
        m1 = ECDSAUtils.build_message("agent_0", [0.5], 1000, 1)
        m2 = ECDSAUtils.build_message("agent_0", [0.5], 1000, 2)
        assert m1 != m2

    def test_hash_message_length(self):
        """哈希 32 字节（SHA-256）"""
        digest = ECDSAUtils.hash_message(b"test")
        assert len(digest) == 32


class TestECDSASignAction:
    def test_sign_action_roundtrip(self):
        """签名包验证往返"""
        priv, pub = ECDSAUtils.generate_key_pair()
        pkg = ECDSAUtils.sign_action("agent_0", priv, [0.5], nonce=3)
        assert ECDSAUtils.verify_action_package(pkg, pub) is True

    def test_sign_action_deterministic(self):
        """确定性签名（RFC6979）：同参数+同 timestamp 签名一致"""
        priv, _ = ECDSAUtils.generate_key_pair()
        # 显式传相同 timestamp（默认取当前毫秒，两次调用可能跨越毫秒边界）
        pkg1 = ECDSAUtils.sign_action("agent_0", priv, [0.5], nonce=3, timestamp=1000)
        pkg2 = ECDSAUtils.sign_action("agent_0", priv, [0.5], nonce=3, timestamp=1000)
        assert pkg1['signature_hex'] == pkg2['signature_hex']

    def test_sign_action_wrong_key_fails(self):
        """错误公钥验签失败"""
        priv, _ = ECDSAUtils.generate_key_pair()
        _, other_pub = ECDSAUtils.generate_key_pair()
        pkg = ECDSAUtils.sign_action("agent_0", priv, [0.5], nonce=3)
        assert ECDSAUtils.verify_action_package(pkg, other_pub) is False


class TestKeyManagerIntegration:
    def test_sign_verify_with_keymanager(self):
        """KeyManager + ECDSA 集成：签名验签往返"""
        key_dir = tempfile.mkdtemp(prefix="test_km_int_")
        try:
            km = KeyManager(key_dir=key_dir)
            priv, pub = km.generate_or_load("agent_0")
            pkg = ECDSAUtils.sign_action("agent_0", priv, [0.1, 0.2], nonce=1)
            assert ECDSAUtils.verify_action_package(pkg, pub) is True
        finally:
            shutil.rmtree(key_dir, ignore_errors=True)

    def test_hex_roundtrip_with_keymanager(self):
        """公钥 hex 往返"""
        key_dir = tempfile.mkdtemp(prefix="test_km_hex2_")
        try:
            km = KeyManager(key_dir=key_dir)
            _, pub = km.generate_or_load("agent_0")
            hex_str = ECDSAUtils.public_key_to_hex(pub)
            restored = ECDSAUtils.public_key_from_hex(hex_str)
            assert restored.public_numbers().x == pub.public_numbers().x
        finally:
            shutil.rmtree(key_dir, ignore_errors=True)

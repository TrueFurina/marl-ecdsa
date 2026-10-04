"""
NetworkConsensusNode 边界测试（RalphLoop 原子任务 Y）
覆盖：投票签名验证（宽松/严格）、统计结构、权重委托、共识模式透传
通过标准：新增 ≥6 项测试全过
"""
import hashlib
import json
import logging
import shutil
import tempfile

import pytest

from blockchain.network.network_consensus import NetworkConsensusNode
from blockchain.crypto.key_manager import KeyManager
from blockchain.crypto.ecdsa_utils import ECDSAUtils

logging.basicConfig(level=logging.CRITICAL)

NODES = ['node_0', 'node_1', 'node_2']


@pytest.fixture
def node():
    """无 key_manager 节点（默认 fail-closed，模拟生产未配置密钥场景）"""
    n = NetworkConsensusNode(
        node_id='node_0', host='127.0.0.1', port=7401,
        all_node_ids=NODES,
    )
    yield n
    # 清理（未 start，无需 stop）


@pytest.fixture
def insecure_node():
    """无 key_manager 但显式开启 insecure 的节点（仅连通性测试用）"""
    n = NetworkConsensusNode(
        node_id='node_0', host='127.0.0.1', port=7409,
        all_node_ids=NODES,
        allow_insecure_vote=True,
    )
    yield n
    # 清理（未 start，无需 stop）


@pytest.fixture
def keyed_node():
    """带 key_manager 节点（严格验证场景）"""
    key_dir = tempfile.mkdtemp(prefix="test_nc_")
    km = KeyManager(key_dir=key_dir)
    for i in range(3):
        km.generate_or_load(f"node_{i}")
    n = NetworkConsensusNode(
        node_id='node_0', host='127.0.0.1', port=7402,
        all_node_ids=NODES, key_manager=km,
    )
    yield n, km
    shutil.rmtree(key_dir, ignore_errors=True)


class TestVerifyVoteSignatureLoose:
    def test_no_sig_no_keymanager_allowed(self, insecure_node):
        """显式 insecure 模式：无 key_manager + 无签名 → 宽松验证通过"""
        assert insecure_node._verify_vote_signature({}, "node_1") is True

    def test_short_sig_rejected(self, insecure_node):
        """显式 insecure 模式：短签名（<64 字节）→ 拒绝"""
        data = {"signature_hex": "abcd"}  # 2 字节
        assert insecure_node._verify_vote_signature(data, "node_1") is False

    def test_valid_length_sig_accepted(self, insecure_node):
        """显式 insecure 模式：64 字节签名 → 宽松通过（仅查格式）"""
        data = {"signature_hex": "ab" * 64}
        assert insecure_node._verify_vote_signature(data, "node_1") is True


class TestVerifyVoteSignatureFailClosed:
    def test_default_node_rejects_unsigned_and_unverifiable_votes(self, node):
        """默认节点无 key_manager 时必须拒绝无签名及仅长度合法的签名。"""
        assert node._verify_vote_signature({}, "node_1") is False
        assert node._verify_vote_signature(
            {"signature_hex": "ab" * 64}, "node_1"
        ) is False


class TestVerifyVoteSignatureStrict:
    def test_no_sig_with_keymanager_rejected(self, keyed_node):
        """有 key_manager + 无签名 → 严格拒绝"""
        node, _ = keyed_node
        assert node._verify_vote_signature({}, "node_1") is False

    def test_valid_signature_accepted(self, keyed_node):
        """有 key_manager + 合法签名 → 通过（P1-7 签名绑定）"""
        node, km = keyed_node
        data = {
            "voter_id": "node_1",
            "block_hash": "hash_abc",
            "phase": "prepare",
            "weight": 1.0,
            "timestamp": 1000,
        }
        verify_data = {k: data[k] for k in ["voter_id", "block_hash", "phase", "weight", "timestamp"]}
        message = hashlib.sha256(json.dumps(verify_data, sort_keys=True).encode()).digest()
        priv = km.get_private_key("node_1")
        data["signature_hex"] = ECDSAUtils.sign(priv, message).hex()
        assert node._verify_vote_signature(data, "node_1") is True

    def test_invalid_signature_rejected(self, keyed_node):
        """有 key_manager + 伪造签名 → 拒绝（身份绑定）"""
        node, _ = keyed_node
        data = {
            "voter_id": "node_1",
            "block_hash": "hash_xyz",
            "phase": "prepare",
            "weight": 1.0,
            "timestamp": 1000,
            "signature_hex": "ff" * 64,  # 伪造签名
        }
        assert node._verify_vote_signature(data, "node_1") is False

    def test_malformed_sig_hex_rejected(self, keyed_node):
        """非法 hex 签名 → 异常捕获返回 False"""
        node, _ = keyed_node
        data = {"voter_id": "node_1", "signature_hex": "not_hex!"}
        assert node._verify_vote_signature(data, "node_1") is False


class TestStatsAndDelegation:
    def test_get_stats_structure(self, node):
        stats = node.get_stats()
        for key in ["node_id", "port", "msg_sent", "msg_received",
                    "consensus_rounds", "network", "weights"]:
            assert key in stats

    def test_update_weight_delegates(self, node):
        node.update_weight("node_1", 0.8)
        assert node.get_weights()["node_1"] == 0.8

    def test_consensus_mode_passthrough(self):
        """consensus_mode 参数透传到节点"""
        n = NetworkConsensusNode(
            node_id='node_0', host='127.0.0.1', port=7403,
            all_node_ids=NODES, consensus_mode='fast',
        )
        assert n.consensus_mode == 'fast'

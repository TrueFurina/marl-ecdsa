"""
A 方案纵深防御：allow_insecure_vote fail-open 加固（DER 结构校验）。

fail-closed 验证目标：
1. insecure 模式『无签名』分支不变（仍放行，仅连通性测试用）。
2. insecure 模式『合法 DER 结构且长度≥64』的签名仍放行（宽松，不真验签）。
3. insecure 模式『长度≥64 但非合法 DER 的垃圾字节』→ 拒绝（A 方案新增纵深防御）。
4. 生产路径（带 key_manager 真验签）完全不受影响：合法签名→True，伪造→False。
5. 异步/批量入口在加固后与同步方法一致（auto == sync，且垃圾字节两侧同判 False）。
6. 批量快速判定 _verify_vote_signature_quick_decision 同样套用 DER 门。

不启动任何 P2P/TLS，纯单元级验证。
"""
import asyncio
import hashlib
import json
import logging
import shutil
import tempfile

import pytest

from blockchain.crypto.ecdsa_utils import ECDSAUtils
from blockchain.crypto.key_manager import KeyManager
from blockchain.network.network_consensus import NetworkConsensusNode

logging.basicConfig(level=logging.CRITICAL)

NODES = ["node_0", "node_1", "node_2"]


def _insecure_node(port=7700):
    return NetworkConsensusNode(
        node_id="node_0", host="127.0.0.1", port=port,
        all_node_ids=NODES, allow_insecure_vote=True,
    )


def _keyed_node(port=7701):
    key_dir = tempfile.mkdtemp(prefix="test_nc_harden_")
    km = KeyManager(key_dir=key_dir)
    for i in range(3):
        km.generate_or_load(f"node_{i}")
    n = NetworkConsensusNode(
        node_id="node_0", host="127.0.0.1", port=port,
        all_node_ids=NODES, key_manager=km,
    )
    return n, km, key_dir


def _valid_der_sig():
    # 结构合法且长度≥64 的 DER 签名（非真实验签，仅用于 insecure 结构门）
    return ECDSAUtils.encode_rs(2 ** 255, 2 ** 255)


def _signed_payload(km, voter_id, *, block_hash, phase, weight=1.0, timestamp=1000,
                    block_height=1, tamper=False):
    data = {
        "voter_id": voter_id, "block_hash": block_hash, "phase": phase,
        "weight": weight, "timestamp": timestamp, "block_height": block_height,
    }
    verify_data = {k: data[k] for k in ["voter_id", "block_hash", "phase", "weight", "timestamp", "block_height"]}
    message = hashlib.sha256(json.dumps(verify_data, sort_keys=True).encode()).digest()
    if tamper:
        data["signature_hex"] = ("ff" * 64)
    else:
        priv = km.get_private_key(voter_id)
        data["signature_hex"] = ECDSAUtils.sign(priv, message).hex()
    return data


class TestInsecureHardening:
    def test_insecure_no_signature_still_true(self):
        """无签名 + insecure → 仍放行（A 方案不触及无签名分支）"""
        n = _insecure_node()
        assert n._verify_vote_signature({}, "node_1") is True

    def test_insecure_valid_der_sig_true(self):
        """合法 DER 结构且长度≥64 → 宽松放行（A 方案后仍成立）"""
        n = _insecure_node()
        data = {"signature_hex": _valid_der_sig().hex()}
        assert n._verify_vote_signature(data, "node_1") is True

    def test_insecure_garbage_sig_false(self):
        """长度≥64 但非合法 DER 的垃圾字节 → 拒绝（A 方案新增纵深防御）"""
        n = _insecure_node()
        data = {"signature_hex": "ab" * 64}
        assert n._verify_vote_signature(data, "node_1") is False

    def test_insecure_short_garbage_false(self):
        """短签名 → 拒绝（A 方案前后一致）"""
        n = _insecure_node()
        data = {"signature_hex": "abcd"}
        assert n._verify_vote_signature(data, "node_1") is False


class TestProductionPathUnchanged:
    def test_valid_signed_vote_true(self):
        """生产路径：带 key_manager 的合法签名 → True（A 方案不影响真验签）"""
        n, km, kd = _keyed_node()
        try:
            data = _signed_payload(km, "node_1", block_hash="h1", phase="prepare")
            assert n._verify_vote_signature(data, "node_1") is True
        finally:
            shutil.rmtree(kd, ignore_errors=True)

    def test_forged_vote_false(self):
        """生产路径：伪造签名 → False（A 方案不影响真验签）"""
        n, km, kd = _keyed_node()
        try:
            data = _signed_payload(km, "node_1", block_hash="h1", phase="prepare", tamper=True)
            assert n._verify_vote_signature(data, "node_1") is False
        finally:
            shutil.rmtree(kd, ignore_errors=True)


class TestAsyncAndBatchConsistency:
    def test_async_matches_sync_on_garbage(self):
        """加固后异步入口与同步方法对垃圾字节同判 False 且一致"""
        n = _insecure_node()
        data = {"signature_hex": "ab" * 64}
        auto = asyncio.run(n._verify_vote_signature_auto(data, "node_1"))
        sync = n._verify_vote_signature(data, "node_1")
        assert auto == sync
        assert sync is False

    def test_quick_decision_hardened(self):
        """批量快速判定同样套用 DER 门：无签名→True、合法DER→True、垃圾→False"""
        n = _insecure_node()
        assert n._verify_vote_signature_quick_decision({}, "node_1") is True
        assert n._verify_vote_signature_quick_decision(
            {"signature_hex": _valid_der_sig().hex()}, "node_1") is True
        assert n._verify_vote_signature_quick_decision(
            {"signature_hex": "ab" * 64}, "node_1") is False

"""
NetworkConsensus 共识投票批量异步验签 offload（opt-in，默认关闭）聚焦测试。

验证目标（fail-closed）：
1. 默认关闭（use_batch_async_verify=False）：_verify_vote_signature_auto 不进入批量分支，
   与原始同步 _verify_vote_signature 逐字等价 —— 零行为改动。
2. 开启（use_batch_async_verify=True）：结果与同步方法一致（功能等价，含合法票 True / 伪造票 False）。
3. 开启时确实走 verify_batch_async 一次（达阈值内联批量；或超时定时器批量），且关闭时绝不走。
4. 失败安全：verify_batch_async 抛异常时整批回退逐票同步，结果正确、无漏检。
5. 顺序保真：混合通过/失败票按到达顺序处理，失败票丢弃。
6. 不弱化验证：伪造签名票在批量路径下仍判 False（P0/P1-7 守护不退化）。

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


@pytest.fixture(scope="module")
def keyed_factory(request):
    """构造带 key_manager 的节点工厂（不 start），用于严格验签分支；自动清理临时密钥目录。"""
    key_dir = tempfile.mkdtemp(prefix="test_nc_batch_")
    km = KeyManager(key_dir=key_dir)
    for i in range(3):
        km.generate_or_load(f"node_{i}")

    def _make(use_batch_async_verify=False, batch_verify_threshold=16,
              batch_verify_flush_timeout=0.002, port=7700, **kw):
        n = NetworkConsensusNode(
            node_id="node_0", host="127.0.0.1", port=port, all_node_ids=NODES,
            key_manager=km,
            use_batch_async_verify=use_batch_async_verify,
            batch_verify_threshold=batch_verify_threshold,
            batch_verify_flush_timeout=batch_verify_flush_timeout,
            **kw,
        )
        n._km_dir = key_dir
        return n, km

    def _fin():
        shutil.rmtree(key_dir, ignore_errors=True)
    request.addfinalizer(_fin)
    return _make


def _signed_payload(km, voter_id, *, block_hash, phase, weight=1.0, timestamp=1000,
                    block_height=1, tamper=False):
    """构造一条合法（或伪造）的签名投票载荷，复用 _broadcast_vote 的签名体对称结构。"""
    data = {
        "voter_id": voter_id,
        "block_hash": block_hash,
        "phase": phase,
        "weight": weight,
        "timestamp": timestamp,
        "block_height": block_height,
    }
    verify_data = {k: data[k] for k in ["voter_id", "block_hash", "phase", "weight", "timestamp", "block_height"]}
    message = hashlib.sha256(json.dumps(verify_data, sort_keys=True).encode()).digest()
    if tamper:
        data["signature_hex"] = ("ff" * 64)
    else:
        priv = km.get_private_key(voter_id)
        data["signature_hex"] = ECDSAUtils.sign(priv, message).hex()
    return data


# ---------------------------------------------------------------------------
# 1) 默认关闭：不进入批量分支，与同步方法逐字等价（零行为改动）
# ---------------------------------------------------------------------------

class TestDefaultOffEquivalence:
    def test_off_never_uses_batch_and_matches_sync(self, keyed_factory, monkeypatch):
        n, km = keyed_factory(use_batch_async_verify=False, port=7701)
        calls = []
        real = ECDSAUtils.verify_batch_async

        async def spy(entries, **kw):
            calls.append(entries)
            return await real(entries, **kw)
        monkeypatch.setattr(ECDSAUtils, "verify_batch_async", spy)

        cases = [
            ({}, "node_1"),
            (_signed_payload(km, "node_1", block_hash="h_a", phase="prepare"), "node_1"),
            (_signed_payload(km, "node_1", block_hash="h_x", phase="prepare", tamper=True), "node_1"),
            (_signed_payload(km, "node_1", block_hash="h_b", phase="commit"), "node_1"),
        ]
        for data, vid in cases:
            got = asyncio.run(n._verify_vote_signature_auto(data, vid))
            exp = n._verify_vote_signature(data, vid)
            assert got == exp, f"默认关闭下 _auto 与同步方法不等价: {data}"
        # 默认关闭绝不能进入批量分支（verify_batch_async 绝不被调用）
        assert calls == [], "默认关闭下不应调用 verify_batch_async"


# ---------------------------------------------------------------------------
# 2) 开启：结果与同步方法一致（功能等价）
# ---------------------------------------------------------------------------

class TestOptInEquivalence:
    def test_optin_matches_sync_battery(self, keyed_factory):
        n, km = keyed_factory(use_batch_async_verify=True, batch_verify_threshold=1,
                              batch_verify_flush_timeout=0.02, port=7702)
        cases = [
            ({}, "node_1"),
            (_signed_payload(km, "node_1", block_hash="h_a", phase="prepare"), "node_1"),
            (_signed_payload(km, "node_1", block_hash="h_x", phase="prepare", tamper=True), "node_1"),
            (_signed_payload(km, "node_1", block_hash="h_b", phase="commit"), "node_1"),
            (_signed_payload(km, "node_1", block_hash="h_c", phase="preprepare", block_height=3), "node_1"),
        ]
        for data, vid in cases:
            got = asyncio.run(n._verify_vote_signature_auto(data, vid))
            exp = n._verify_vote_signature(data, vid)
            assert got == exp, f"开启批量后结果与同步方法不一致: {data}"

    def test_optin_valid_true_and_forged_false(self, keyed_factory):
        n, km = keyed_factory(use_batch_async_verify=True, batch_verify_threshold=1,
                              batch_verify_flush_timeout=0.02, port=7703)
        good = _signed_payload(km, "node_1", block_hash="h_ok", phase="prepare")
        bad = _signed_payload(km, "node_1", block_hash="h_bad", phase="prepare", tamper=True)
        assert asyncio.run(n._verify_vote_signature_auto(good, "node_1")) is True
        assert asyncio.run(n._verify_vote_signature_auto(bad, "node_1")) is False


# ---------------------------------------------------------------------------
# 3) 批量接线：达阈值内联批量 / 超时定时器批量；关闭时绝不走
# ---------------------------------------------------------------------------

class TestBatchWiring:
    def test_threshold_inline_uses_verify_batch_async_once(self, keyed_factory, monkeypatch):
        n, km = keyed_factory(use_batch_async_verify=True, batch_verify_threshold=2,
                              batch_verify_flush_timeout=10.0, port=7704)
        calls = []
        real = ECDSAUtils.verify_batch_async

        async def spy(entries, **kw):
            calls.append(entries)
            return await real(entries, **kw)
        monkeypatch.setattr(ECDSAUtils, "verify_batch_async", spy)

        d1 = _signed_payload(km, "node_1", block_hash="h1", phase="prepare")
        d2 = _signed_payload(km, "node_1", block_hash="h2", phase="prepare")

        async def run_two():
            t1 = asyncio.ensure_future(n._verify_vote_signature_auto(d1, "node_1"))
            t2 = asyncio.ensure_future(n._verify_vote_signature_auto(d2, "node_1"))
            return await asyncio.gather(t1, t2)

        r1, r2 = asyncio.run(run_two())
        assert (r1, r2) == (True, True)
        # 达阈值(2)内联批量：verify_batch_async 仅被调用一次，且含 2 条验签
        assert len(calls) == 1, f"阈值触发应内联批量一次，实际调用 {len(calls)} 次"
        assert len(calls[0]) == 2, f"批量应含 2 条验签，实际 {len(calls[0])}"

    def test_timer_uses_verify_batch_async_once(self, keyed_factory, monkeypatch):
        n, km = keyed_factory(use_batch_async_verify=True, batch_verify_threshold=100,
                              batch_verify_flush_timeout=0.05, port=7705)
        calls = []
        real = ECDSAUtils.verify_batch_async

        async def spy(entries, **kw):
            calls.append(entries)
            return await real(entries, **kw)
        monkeypatch.setattr(ECDSAUtils, "verify_batch_async", spy)

        d = _signed_payload(km, "node_1", block_hash="ht", phase="prepare")

        async def run_one():
            return await n._verify_vote_signature_auto(d, "node_1")

        assert asyncio.run(run_one()) is True
        # 单票未达阈值 -> 定时器触发批量：verify_batch_async 被调用一次且含 1 条验签
        assert len(calls) == 1, f"定时器应触发批量一次，实际 {len(calls)} 次"
        assert len(calls[0]) == 1


# ---------------------------------------------------------------------------
# 4) 失败安全：verify_batch_async 抛异常时整批回退逐票同步
# ---------------------------------------------------------------------------

class TestFailSafeFallback:
    def test_batch_exception_falls_back_to_sync(self, keyed_factory, monkeypatch):
        n, km = keyed_factory(use_batch_async_verify=True, batch_verify_threshold=1,
                              batch_verify_flush_timeout=10.0, port=7706)

        async def boom(entries, **kw):
            raise RuntimeError("injected batch failure")
        monkeypatch.setattr(ECDSAUtils, "verify_batch_async", boom)

        good = _signed_payload(km, "node_1", block_hash="hf", phase="prepare")
        bad = _signed_payload(km, "node_1", block_hash="hf2", phase="prepare", tamper=True)
        # 回退必须给出与同步方法一致的正确结果（绝不漏检伪造票）
        assert asyncio.run(n._verify_vote_signature_auto(good, "node_1")) is True
        assert asyncio.run(n._verify_vote_signature_auto(bad, "node_1")) is False

    def test_fallback_matches_sync_on_mixed(self, keyed_factory, monkeypatch):
        n, km = keyed_factory(use_batch_async_verify=True, batch_verify_threshold=4,
                              batch_verify_flush_timeout=10.0, port=7707)
        cases = [
            (_signed_payload(km, "node_1", block_hash="m1", phase="prepare"), "node_1"),
            (_signed_payload(km, "node_1", block_hash="m2", phase="prepare", tamper=True), "node_1"),
            (_signed_payload(km, "node_1", block_hash="m3", phase="prepare"), "node_1"),
            ({}, "node_1"),  # 无签名 + key_manager 存在 -> 同步 False
        ]

        async def boom(entries, **kw):
            raise RuntimeError("injected batch failure")
        monkeypatch.setattr(ECDSAUtils, "verify_batch_async", boom)

        for data, vid in cases:
            got = asyncio.run(n._verify_vote_signature_auto(data, vid))
            exp = n._verify_vote_signature(data, vid)
            assert got == exp, f"回退结果与同步方法不一致: {data}"


# ---------------------------------------------------------------------------
# 5) 顺序保真 + 不弱化验证：混合通过/失败票按到达顺序处理，失败票丢弃
# ---------------------------------------------------------------------------

class TestOrderingFidelity:
    def test_order_preserved_and_forged_dropped(self, keyed_factory, monkeypatch):
        n, km = keyed_factory(use_batch_async_verify=True, batch_verify_threshold=4,
                              batch_verify_flush_timeout=10.0, port=7708)
        calls = []
        real = ECDSAUtils.verify_batch_async

        async def spy(entries, **kw):
            calls.append(entries)
            return await real(entries, **kw)
        monkeypatch.setattr(ECDSAUtils, "verify_batch_async", spy)

        d_valid_1 = _signed_payload(km, "node_1", block_hash="o1", phase="prepare")
        d_forged_1 = _signed_payload(km, "node_1", block_hash="o2", phase="prepare", tamper=True)
        d_valid_2 = _signed_payload(km, "node_1", block_hash="o3", phase="prepare")
        d_forged_2 = _signed_payload(km, "node_1", block_hash="o4", phase="prepare", tamper=True)

        async def run_four():
            t1 = asyncio.ensure_future(n._verify_vote_signature_auto(d_valid_1, "node_1"))
            t2 = asyncio.ensure_future(n._verify_vote_signature_auto(d_forged_1, "node_1"))
            t3 = asyncio.ensure_future(n._verify_vote_signature_auto(d_valid_2, "node_1"))
            t4 = asyncio.ensure_future(n._verify_vote_signature_auto(d_forged_2, "node_1"))
            return await asyncio.gather(t1, t2, t3, t4)

        results = asyncio.run(run_four())
        # 顺序保真：每张票拿到各自正确结果；伪造票判 False（不弱化验证）
        assert results == [True, False, True, False], f"顺序/结果不符: {results}"
        # 批量仅调用一次且含 4 条，按到达顺序
        assert len(calls) == 1 and len(calls[0]) == 4

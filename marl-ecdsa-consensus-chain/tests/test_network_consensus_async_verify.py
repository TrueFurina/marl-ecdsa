"""
NetworkConsensus 共识验签异步 offload（opt-in，默认关闭）聚焦测试。

验证目标（fail-closed）：
1. 默认关闭（use_async_verify=False）：_verify_vote_signature_auto 与原始同步
   _verify_vote_signature 对全部输入逐字等价 —— 零行为改动。
2. 开启（use_async_verify=True）：_verify_vote_signature_auto 结果与同步方法一致
   —— 异步路径功能等价。
3. 开启时异步路径确实把 ECDSA 验签 offload 到 worker 线程（asyncio.to_thread），
   且关闭时绝不 offload（开关门控正确）。
4. 三处共识处理器（_on_preprepare / _on_prepare / _on_commit）已接线
   ``await self._verify_vote_signature_auto``，防止误回退到裸同步调用。

不启动任何 P2P/TLS，纯单元级验证。
"""
import asyncio
import hashlib
import json
import logging
import threading
import time

import pytest

from blockchain.crypto.ecdsa_utils import ECDSAUtils
from blockchain.crypto.key_manager import KeyManager
from blockchain.network.network_consensus import NetworkConsensusNode

logging.basicConfig(level=logging.CRITICAL)

NODES = ["node_0", "node_1", "node_2"]


def _make_keyed_node(use_async_verify: bool, port: int = 7600):
    """构造带 key_manager 的节点（不 start），用于严格验签分支。"""
    import shutil
    import tempfile

    key_dir = tempfile.mkdtemp(prefix="test_nc_async_")
    km = KeyManager(key_dir=key_dir)
    for i in range(3):
        km.generate_or_load(f"node_{i}")
    n = NetworkConsensusNode(
        node_id="node_0",
        host="127.0.0.1",
        port=port,
        all_node_ids=NODES,
        key_manager=km,
        use_async_verify=use_async_verify,
    )
    n._km_dir = key_dir  # 便于清理
    return n, km


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
# 1) 默认关闭：与同步方法逐字等价
# ---------------------------------------------------------------------------

class TestDefaultOffEquivalence:
    def test_off_matches_sync_on_insecure_battery(self):
        insecure = NetworkConsensusNode(
            node_id="node_0", host="127.0.0.1", port=7611, all_node_ids=NODES,
            allow_insecure_vote=True, use_async_verify=False,
        )
        cases = [
            ({}, "node_1"),                                  # 无签名 + insecure
            ({"signature_hex": "ab" * 64}, "node_1"),         # 64 字节长签名 + insecure
            ({"signature_hex": "abcd"}, "node_1"),            # 短签名 + insecure
        ]
        for data, vid in cases:
            assert asyncio.run(insecure._verify_vote_signature_auto(data, vid)) == \
                insecure._verify_vote_signature(data, vid), \
                f"默认关闭下 _auto 与同步方法不等价: {data}"

    def test_off_matches_sync_on_keyed_battery(self):
        n, km = _make_keyed_node(use_async_verify=False, port=7612)
        cases = [
            ({}, "node_1"),
            (_signed_payload(km, "node_1", block_hash="h_a", phase="prepare"), "node_1"),
            (_signed_payload(km, "node_1", block_hash="h_x", phase="prepare", tamper=True), "node_1"),
            (_signed_payload(km, "node_1", block_hash="h_b", phase="commit"), "node_1"),
        ]
        for data, vid in cases:
            assert asyncio.run(n._verify_vote_signature_auto(data, vid)) == \
                n._verify_vote_signature(data, vid), \
                f"默认关闭下 _auto 与同步方法不等价: {data}"


# ---------------------------------------------------------------------------
# 2) 开启：结果与同步方法一致（功能等价）
# ---------------------------------------------------------------------------

class TestOptInEquivalence:
    def test_optin_matches_sync_on_keyed_battery(self):
        n, km = _make_keyed_node(use_async_verify=True, port=7613)
        cases = [
            ({}, "node_1"),
            (_signed_payload(km, "node_1", block_hash="h_a", phase="prepare"), "node_1"),
            (_signed_payload(km, "node_1", block_hash="h_x", phase="prepare", tamper=True), "node_1"),
            (_signed_payload(km, "node_1", block_hash="h_b", phase="commit"), "node_1"),
        ]
        for data, vid in cases:
            assert asyncio.run(n._verify_vote_signature_auto(data, vid)) == \
                n._verify_vote_signature(data, vid), \
                f"开启异步后结果与同步方法不一致: {data}"

    def test_optin_valid_sig_true_and_forged_false(self):
        n, km = _make_keyed_node(use_async_verify=True, port=7614)
        good = _signed_payload(km, "node_1", block_hash="h_ok", phase="prepare")
        bad = _signed_payload(km, "node_1", block_hash="h_bad", phase="prepare", tamper=True)
        assert asyncio.run(n._verify_vote_signature_auto(good, "node_1")) is True
        assert asyncio.run(n._verify_vote_signature_auto(bad, "node_1")) is False


# ---------------------------------------------------------------------------
# 3) 开启时 offload 到 worker 线程；关闭时绝不 offload
# ---------------------------------------------------------------------------

class TestOffloadWiring:
    def test_optin_offloads_to_worker_thread(self, monkeypatch):
        info = {"call_thread": None, "worker_thread": None, "called": 0}

        async def fake_vca(pub, msg, sig):
            info["call_thread"] = threading.current_thread()

            def _worker():
                info["worker_thread"] = threading.current_thread()
                return ECDSAUtils.verify_cached(pub, msg, sig)

            info["called"] += 1
            return await asyncio.to_thread(_worker)

        monkeypatch.setattr(ECDSAUtils, "verify_cached_async", fake_vca)

        n, km = _make_keyed_node(use_async_verify=True, port=7615)
        good = _signed_payload(km, "node_1", block_hash="h_off", phase="prepare")
        result = asyncio.run(n._verify_vote_signature_auto(good, "node_1"))

        assert result is True
        assert info["called"] == 1, "开启后未调用异步验签原语 verify_cached_async"
        assert info["worker_thread"] is not None
        assert info["worker_thread"] is not info["call_thread"], \
            "异步验签未 offload 到 worker 线程（仍在调用线程执行）"
        assert "ThreadPool" in info["worker_thread"].name or \
            info["worker_thread"] is not threading.main_thread(), \
            "异步验签应运行在 worker 线程而非主线程"

    def test_default_off_does_not_offload(self, monkeypatch):
        info = {"called": 0}

        async def fake_vca(pub, msg, sig):
            info["called"] += 1
            return ECDSAUtils.verify_cached(pub, msg, sig)

        monkeypatch.setattr(ECDSAUtils, "verify_cached_async", fake_vca)

        n, km = _make_keyed_node(use_async_verify=False, port=7616)
        good = _signed_payload(km, "node_1", block_hash="h_nooff", phase="prepare")
        result = asyncio.run(n._verify_vote_signature_auto(good, "node_1"))

        # 默认关闭：结果仍正确，但异步原语绝不被调用（走原同步路径）
        assert result is True
        assert info["called"] == 0, "默认关闭下不应调用异步验签原语 verify_cached_async"


# ---------------------------------------------------------------------------
# 4) 三处共识处理器接线正确
# ---------------------------------------------------------------------------

class TestHandlerWiring:
    def test_handlers_await_verify_auto(self):
        n = NetworkConsensusNode(
            node_id="node_0", host="127.0.0.1", port=7617, all_node_ids=NODES,
        )
        import inspect

        for handler in (n._on_preprepare, n._on_prepare, n._on_commit):
            src = inspect.getsource(handler)
            assert "await self._verify_vote_signature_auto" in src, \
                f"{handler.__name__} 未接线 await self._verify_vote_signature_auto"


# ---------------------------------------------------------------------------
# 5) 事件循环响应性（确定性证明 offload 释放 event loop，无需抖动计时）
# ---------------------------------------------------------------------------

class TestEventLoopResponsive:
    def test_async_keeps_loop_responsive_while_sync_blocks(self):
        """确定性验证：同步验签在 event loop 线程内阻塞循环；异步 offload 释放循环。

        方法：在运行验签批处理的同时启动一个心跳协程（每轮 yield 一次即 +1）。
        同步路径（默认关闭）把验签作为 CPU 密集调用阻塞在 loop 线程，心跳在批处理
        期间几乎不推进；异步路径把验签 offload 到 worker 线程，loop 在等待期间持续
        运行心跳。由此确定性地证明 offload 达成其设计目的，不依赖易抖动的计时断言。
        """
        n_sync, km_sync = _make_keyed_node(use_async_verify=False, port=7620)
        n_async, km_async = _make_keyed_node(use_async_verify=True, port=7621)
        good_sync = _signed_payload(km_sync, "node_1", block_hash="h_resp", phase="prepare")
        good_async = _signed_payload(km_async, "node_1", block_hash="h_resp", phase="prepare")

        async def measure(node, payload):
            counter = {"n": 0}

            async def heartbeat():
                while True:
                    counter["n"] += 1
                    await asyncio.sleep(0)

            hb = asyncio.create_task(heartbeat())
            for _ in range(50):
                await node._verify_vote_signature_auto(payload, "node_1")
            final = counter["n"]  # 仅在批处理期间计数（批后 cancel 不计入）
            hb.cancel()
            try:
                await hb
            except asyncio.CancelledError:
                pass
            return final

        sync_hb = asyncio.run(measure(n_sync, good_sync))
        async_hb = asyncio.run(measure(n_async, good_async))

        # 异步路径必须让 event loop 在验签期间持续响应（心跳显著推进）
        assert async_hb > 5, f"异步路径未释放 event loop（批处理期间心跳仅 {async_hb}）"
        # 确定性：异步心跳数应明显高于同步（同步在 loop 内阻塞，心跳几乎不推进）
        assert async_hb > sync_hb, \
            f"异步路径未比同步更释放 loop：sync_hb={sync_hb}, async_hb={async_hb}"


# ---------------------------------------------------------------------------
# 6) 吞吐基准（信息性；硬断言仅覆盖完成与一致性，不依赖易抖动计时）
# ---------------------------------------------------------------------------

class TestThroughputBaseline:
    def test_sync_vs_async_throughput_reports(self):
        """对比同步/异步验签批处理墙钟时间，输出基准表供后续'翻开关'评审参考。

        硬断言仅覆盖：两条路径均能完成且结果一致（功能等价）；异步确实 offload
        （已由 TestOffloadWiring 覆盖）。计时不作硬性断言，避免 CI 抖动。
        """
        n_sync, km_sync = _make_keyed_node(use_async_verify=False, port=7622)
        n_async, km_async = _make_keyed_node(use_async_verify=True, port=7623)
        good_sync = _signed_payload(km_sync, "node_1", block_hash="h_bench", phase="prepare")
        good_async = _signed_payload(km_async, "node_1", block_hash="h_bench", phase="prepare")
        K = 100

        async def batch(node, payload):
            for _ in range(K):
                await node._verify_vote_signature_auto(payload, "node_1")

        t0 = time.perf_counter()
        asyncio.run(batch(n_sync, good_sync))
        t_sync = time.perf_counter() - t0

        t0 = time.perf_counter()
        asyncio.run(batch(n_async, good_async))
        t_async = time.perf_counter() - t0

        # 功能等价（两条路径结果一致）
        assert asyncio.run(n_sync._verify_vote_signature_auto(good_sync, "node_1")) is True
        assert asyncio.run(n_async._verify_vote_signature_auto(good_async, "node_1")) is True

        print(f"\n[bench] verify x{K}: sync={t_sync*1e3:.2f}ms  "
              f"async={t_async*1e3:.2f}ms  (async/sync={t_async/max(t_sync,1e-9):.2f}x)")


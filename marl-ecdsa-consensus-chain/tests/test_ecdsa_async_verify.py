"""
ECDSA 异步验签 offload 原语 自验收测试（2026-11-10 自进化，backlog#1 安全子集）

backlog#1 根因：共识热路径逐票同步验签阻塞 event loop（O(n^2) 串行）。
本测试只覆盖**安全子集**——提供异步 offload 原语 verify_cached_async /
verify_batch_async（网络层调用点接入属 needs-design，本测试不触碰）。

验证：
  1. verify_cached_async 正确性 == 同步 verify_cached（合法 True / 非法 False）。
  2. verify_cached_async 确实把验签 offload 到 worker 线程（非调用/事件循环线程）。
  3. verify_batch_async 结果与同步 verify_batch 逐条一致（合法/非法混合）。
  4. verify_batch_async 同样 offload 到 worker 线程。
"""
import asyncio
import threading

from cryptography.hazmat.primitives.asymmetric import ec

from blockchain.crypto.ecdsa_utils import ECDSAUtils


def _make_key():
    priv = ec.generate_private_key(ec.SECP256R1())
    return priv, priv.public_key()


def test_verify_cached_async_matches_sync():
    priv, pub = _make_key()
    msg = b"consensus-vote-payload"
    sig = ECDSAUtils.sign(priv, msg)
    ok_async = asyncio.run(ECDSAUtils.verify_cached_async(pub, msg, sig))
    ok_sync = ECDSAUtils.verify_cached(pub, msg, sig)
    assert ok_async is True
    assert ok_async == ok_sync
    # 非法：篡改消息应判 False
    bad_async = asyncio.run(ECDSAUtils.verify_cached_async(pub, b"tampered", sig))
    assert bad_async is False


def test_verify_cached_async_offloads_to_worker_thread():
    """关键断言：验签必须在 worker 线程执行，而非调用（事件循环）线程。"""
    priv, pub = _make_key()
    msg = b"offload-check"
    sig = ECDSAUtils.sign(priv, msg)

    seen = {}
    orig = ECDSAUtils.verify_cached

    def spy(pk, m, s):
        seen["thread"] = threading.current_thread()
        return orig(pk, m, s)

    ECDSAUtils.verify_cached = staticmethod(spy)
    try:
        res = asyncio.run(ECDSAUtils.verify_cached_async(pub, msg, sig))
    finally:
        ECDSAUtils.verify_cached = staticmethod(orig)

    assert res is True
    assert seen["thread"] is not None
    assert seen["thread"] is not threading.current_thread()  # 已 offload
    assert seen["thread"].name != threading.current_thread().name


def _entries(priv, pub):
    return [
        (pub, b"m1", ECDSAUtils.sign(priv, b"m1")),   # True
        (pub, b"m2", b"not-a-valid-signature"),        # False
        (pub, b"m3", ECDSAUtils.sign(priv, b"m3")),   # True
        (pub, b"m4", ECDSAUtils.sign(priv, b"m4")),   # True
    ]


def test_verify_batch_async_matches_sync():
    priv, pub = _make_key()
    entries = _entries(priv, pub)
    expected = ECDSAUtils.verify_batch(entries, use_cache=True)
    got = asyncio.run(ECDSAUtils.verify_batch_async(entries, use_cache=True))
    assert got == expected
    assert got == [True, False, True, True]


def test_verify_batch_async_offloads_to_worker_thread():
    priv, pub = _make_key()
    entries = _entries(priv, pub)

    seen = set()
    orig = ECDSAUtils.verify_cached

    def spy(pk, m, s):
        seen.add(threading.current_thread().name)
        return orig(pk, m, s)

    ECDSAUtils.verify_cached = staticmethod(spy)
    try:
        got = asyncio.run(ECDSAUtils.verify_batch_async(entries, use_cache=True))
    finally:
        ECDSAUtils.verify_cached = staticmethod(orig)

    assert got == [True, False, True, True]
    # 至少一条在 worker 线程执行（主线程名不应出现）
    assert threading.current_thread().name not in seen

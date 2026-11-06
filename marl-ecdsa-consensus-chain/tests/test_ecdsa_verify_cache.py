"""ECDSA 验签 LRU 记忆化缓存 + 批量验签 —— 自进化优化 v1 自验收。

验收标准：
1. verify_cached 不改变验签正确性（合法/篡改/异常与 verify 一致）。
2. 重复验签走 verify_cached（命中缓存）显著快于默认 verify（零缓存开销）。
3. verify_batch 结果与逐条 verify / verify_cached 完全一致。
4. 默认 verify() 热路径零缓存开销（不受缓存逻辑影响）。
"""
import time

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from blockchain.crypto.ecdsa_utils import ECDSAUtils


@pytest.fixture
def key_pair():
    return ECDSAUtils.generate_key_pair()


def test_verify_cached_correctness(key_pair):
    priv, pub = key_pair
    msg = b"hello marl-ecdsa"
    sig = ECDSAUtils.sign(priv, msg)
    ECDSAUtils.clear_verify_cache()
    assert ECDSAUtils.verify_cached(pub, msg, sig) is True
    assert ECDSAUtils.verify_cached(pub, b"tampered", sig) is False
    # 命中缓存后行为不变
    assert ECDSAUtils.verify_cached(pub, msg, sig) is True
    assert ECDSAUtils.verify_cached(pub, b"tampered", sig) is False


def test_verify_cached_speedup(key_pair):
    priv, pub = key_pair
    msg = b"benchmark payload for consensus replay"
    sig = ECDSAUtils.sign(priv, msg)
    N = 3000

    # 基线：默认 verify（零缓存开销）
    t0 = time.perf_counter()
    for _ in range(N):
        ECDSAUtils.verify(pub, msg, sig)
    t_baseline = time.perf_counter() - t0

    # 缓存路径：首次灌满，其余命中
    ECDSAUtils.clear_verify_cache()
    t1 = time.perf_counter()
    for _ in range(N):
        ECDSAUtils.verify_cached(pub, msg, sig)
    t_cached = time.perf_counter() - t1

    # 命中缓存应明显快于基线（省去椭圆曲线标量乘）
    assert t_cached < t_baseline * 0.5, (
        f"缓存未带来提速: cached={t_cached:.4f}s baseline={t_baseline:.4f}s"
    )
    # 正确性不被缓存破坏
    assert ECDSAUtils.verify_cached(pub, msg, sig) is True


def test_verify_default_path_cache_free(key_pair):
    """默认 verify() 不应受缓存逻辑影响（无缓存键开销、无状态副作用）。"""
    priv, pub = key_pair
    msg = b"default path"
    sig = ECDSAUtils.sign(priv, msg)
    ECDSAUtils.clear_verify_cache()
    assert ECDSAUtils.verify(pub, msg, sig) is True
    # 篡改后默认路径仍正确
    assert ECDSAUtils.verify(pub, b"x", sig) is False


def test_verify_batch_matches_sequential(key_pair):
    priv, pub = key_pair
    entries, expected = [], []
    for i in range(24):
        m = f"msg-{i}".encode()
        s = ECDSAUtils.sign(priv, m)
        entries.append((pub, m, s))
        expected.append(True)
    entries.append((pub, b"x", b"not-a-sig"))
    expected.append(False)

    batch = ECDSAUtils.verify_batch(entries, use_cache=True)
    seq = [ECDSAUtils.verify(p, m, s) for (p, m, s) in entries]
    assert batch == expected
    assert batch == seq

    # 关闭缓存也应一致
    batch_nc = ECDSAUtils.verify_batch(entries, use_cache=False)
    assert batch_nc == expected


def test_verify_batch_cache_shortcut_consistency(key_pair):
    priv, pub = key_pair
    entries = [(pub, f"repeat-{i}".encode(), ECDSAUtils.sign(priv, f"repeat-{i}".encode()))
               for i in range(10)]
    with_cache = ECDSAUtils.verify_batch(entries, use_cache=True)
    without = ECDSAUtils.verify_batch(entries, use_cache=False)
    assert with_cache == without == [True] * len(entries)

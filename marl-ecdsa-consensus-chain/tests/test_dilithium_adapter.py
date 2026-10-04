"""
后量子签名适配器测试
====================
覆盖：接口契约、真实 Dilithium 签名往返、**回落检测**、混合签名 AND 策略、实测基准。

关键设计：`test_*_catches_fallback` 类测试专门用于识别「静默回落 ECDSA」——
若适配器声称后量子却实际调用 ECDSA，这些断言必然失败。
"""
import importlib.util
import logging

import pytest

from blockchain.crypto.dilithium_adapter import (
    DILITHIUM_AVAILABLE,
    DILITHIUM_SIGNATURE_SIZE,
    ECDSAAdapter,
    DilithiumAdapter,
    HybridSignatureAdapter,
    SignatureAdapter,
    benchmark_signature_adapters,
)

logging.basicConfig(level=logging.CRITICAL)


class TestAdapterInterface:
    def test_abc_interface(self):
        """SignatureAdapter 为抽象基类，含 sign/verify/get_algorithm_name"""
        assert SignatureAdapter.__abstractmethods__  # 至少含抽象方法

    def test_ecdsa_adapter(self):
        a = ECDSAAdapter()
        assert a.get_algorithm_name().startswith('ECDSA')
        assert a.get_security_level()  # 非空

    def test_dilithium_adapter_exists(self):
        a = DilithiumAdapter()
        # 名称中始终含 Dilithium 标识（真实或回落）
        assert 'dilithium' in a.get_algorithm_name().lower()
        assert a.get_security_level()


class TestAdapterBehavior:
    def test_sign_verify_roundtrip(self):
        """适配器 sign→verify 往返一致；篡改消息应失败"""
        for adapter_cls in [ECDSAAdapter, DilithiumAdapter]:
            a = adapter_cls()
            priv, pub = a.generate_key_pair()
            msg = b'post-quantum adapter test'
            sig = a.sign(priv, msg)
            assert a.verify(pub, msg, sig) is True
            assert a.verify(pub, b'tampered', sig) is False


def _backend_installed() -> bool:
    """dilithium-py 是否真的可导入（与适配器开关解耦）"""
    try:
        return importlib.util.find_spec('dilithium_py.ml_dsa') is not None
    except ModuleNotFoundError:
        return False


@pytest.mark.skipif(not _backend_installed(), reason="dilithium-py 未安装，真实后量子断言不适用")
class TestRealDilithium:
    """后端可用时，验证执行的是**真实** ML-DSA，而非 ECDSA 回落。

    注意：仅当 `dilithium-py` **确实缺失** 才跳过；若库已安装但开关被关掉，
    下面的 test_backend_enabled_when_installed 会**失败**，从而暴露静默降级。
    """

    def test_backend_enabled_when_installed(self):
        """库已安装 → DILITHIUM_AVAILABLE 必须为 True（防静默降级）"""
        assert DILITHIUM_AVAILABLE, (
            'dilithium-py 已安装但 DILITHIUM_AVAILABLE=False —— 后量子能力被静默关闭'
        )

    def test_signature_size_is_ml_dsa(self):
        """签名长度必须是 ML-DSA-44 的 2420B —— ECDSA 回落约 70B，可据此抓回落"""
        a = DilithiumAdapter()
        sk, pk = a.generate_key_pair()
        sig = a.sign(sk, b'size check')
        assert len(sig) == DILITHIUM_SIGNATURE_SIZE

    def test_public_key_size_is_ml_dsa(self):
        a = DilithiumAdapter()
        sk, pk = a.generate_key_pair()
        assert len(pk) == 1312

    def test_randomized_signature_catches_ecdsa_fallback(self):
        """ML-DSA 默认随机化：同一消息两次签名应不同。
        RFC 6979 的 ECDSA 是确定性的（两次签名完全相同）→ 若相同即为回落。"""
        a = DilithiumAdapter()
        sk, pk = a.generate_key_pair()
        msg = b'determinism probe'
        assert a.sign(sk, msg) != a.sign(sk, msg)

    def test_wrong_key_rejected(self):
        a = DilithiumAdapter()
        sk1, _ = a.generate_key_pair()
        _, pk2 = a.generate_key_pair()
        sig = a.sign(sk1, b'cross key')
        assert a.verify(pk2, b'cross key', sig) is False

    def test_malformed_signature_rejected(self):
        """非法长度签名不得抛异常，必须返回 False"""
        a = DilithiumAdapter()
        _, pk = a.generate_key_pair()
        assert a.verify(pk, b'msg', b'\x00' * 10) is False

    def test_availability_flag_and_security_level_consistent(self):
        a = DilithiumAdapter()
        assert a.is_quantum_resistant is True
        assert 'quantum-resistant' in a.get_security_level().lower()
        readiness = a.get_migration_readiness()
        assert readiness['available'] is True
        assert readiness['quantum_resistant'] is True
        assert readiness['fallback_active'] is False


class TestFallbackHonesty:
    """无后端时，必须如实标注为回落，不得声称抗量子。"""

    def test_fallback_security_level_is_honest(self):
        a = DilithiumAdapter()
        level = a.get_security_level().lower()
        if DILITHIUM_AVAILABLE:
            assert 'quantum-resistant' in level
        else:
            assert 'shor-vulnerable' in level or '未实现' in level

    def test_disable_fallback_raises_without_backend(self):
        if DILITHIUM_AVAILABLE:
            pytest.skip("后端可用，回落路径不适用")
        with pytest.raises(ImportError):
            DilithiumAdapter(use_fallback=False)


class TestHybridSignature:
    def test_hybrid_and_policy(self):
        """混合签名：两者都对才通过；任一被篡改即失败"""
        h = HybridSignatureAdapter()
        epriv, epub = h._ecdsa.generate_key_pair()
        dsk, dpk = h._dilithium.generate_key_pair()
        msg = b'hybrid message'
        s = h.hybrid_sign(epriv, dsk, msg)
        assert h.hybrid_verify(epub, dpk, msg, s['ecdsa_signature'], s['dilithium_signature']) is True
        # 篡改消息 → 双双失败
        assert h.hybrid_verify(epub, dpk, b'other', s['ecdsa_signature'], s['dilithium_signature']) is False

    def test_hybrid_reports_quantum_status_from_backend(self):
        h = HybridSignatureAdapter()
        assert h.get_transition_status()['quantum_resistant'] == h.is_hybrid_quantum_resistant


class TestBenchmark:
    def test_benchmark_measured_only_when_available(self):
        """后端可用 → Dilithium 行必须标记 measured=True；不可用 → measured=False 且不填数字"""
        rows = benchmark_signature_adapters(num_iterations=5)['adapters']
        dil_rows = [r for r in rows if r['algorithm'].startswith('ML-DSA')]
        assert dil_rows, '缺少 Dilithium 基准行'
        row = dil_rows[0]
        if DILITHIUM_AVAILABLE:
            assert row.get('measured') is True
            assert row['sig_size_bytes'] == DILITHIUM_SIGNATURE_SIZE
        else:
            assert row.get('measured') is False
            assert 'sign_ms' not in row  # 不得填充估计值

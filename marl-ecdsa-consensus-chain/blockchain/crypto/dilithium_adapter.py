"""
Post-Quantum Signature Adapter — ECDSA ↔ CRYSTALS-Dilithium (ML-DSA-44)
======================================================================
统一签名接口，支持：
  1. 算法可换：ECDSA-secp256r1 (FIPS 186-5) ↔ **ML-DSA-44（CRYSTALS-Dilithium2, FIPS 204）**
  2. 混合双签名（ECDSA + Dilithium，AND 策略）—— 迁移期纵深防御
  3. 性能对比：**本机实测**（不再有硬编码估计值）

后端：`dilithium-py`（纯 Python 的 ML-DSA 实现，无编译依赖）
  未安装时 DilithiumAdapter 按 use_fallback 决定回落 ECDSA 或直接报错；
  真实可用性由 get_migration_readiness() 动态查询，**不再硬编码**。

状态（2026-09-18）：**已实现**。后端可用时执行真实后量子签名与验签，
签名为 2420 字节（ML-DSA-44），具备 NIST Level 2 抗量子能力。

CCF 5th Blockchain Competition | V4.2 | Phase 2: Post-Quantum Migration (implemented)
"""
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# 后端可用性：真实探测（不硬编码）
# -----------------------------------------------------------------------------
try:  # pragma: no cover - 依赖环境
    from dilithium_py.ml_dsa import ML_DSA_44 as _ML_DSA_44

    DILITHIUM_AVAILABLE = True
    DILITHIUM_BACKEND = "dilithium-py (ML-DSA-44)"
except ImportError:  # pragma: no cover
    _ML_DSA_44 = None
    DILITHIUM_AVAILABLE = False
    DILITHIUM_BACKEND = None

# ML-DSA-44 参数（FIPS 204）
DILITHIUM_SIGNATURE_SIZE = 2420
DILITHIUM_PUBLIC_KEY_SIZE = 1312
DILITHIUM_PRIVATE_KEY_SIZE = 2560


class SignatureAdapter(ABC):
    """签名算法统一接口。"""

    @abstractmethod
    def generate_key_pair(self) -> Tuple[Any, Any]:
        """生成密钥对，返回 (私钥, 公钥)。"""

    @abstractmethod
    def sign(self, private_key: Any, message: bytes) -> bytes:
        """用私钥对消息签名。"""

    @abstractmethod
    def verify(self, public_key: Any, message: bytes, signature: bytes) -> bool:
        """用公钥验签。"""

    @abstractmethod
    def get_algorithm_name(self) -> str:
        """算法名（用于报告）。"""

    @abstractmethod
    def get_security_level(self) -> str:
        """安全级别描述。"""


class ECDSAAdapter(SignatureAdapter):
    """ECDSA secp256r1（FIPS 186-5，经典 128-bit 安全，不抗量子）。"""

    def __init__(self):
        from blockchain.crypto.ecdsa_utils import ECDSAUtils

        self._utils = ECDSAUtils

    def generate_key_pair(self) -> Tuple[Any, Any]:
        return self._utils.generate_key_pair()

    def sign(self, private_key, message: bytes) -> bytes:
        return self._utils.sign(private_key, message)

    def verify(self, public_key, message: bytes, signature: bytes) -> bool:
        return self._utils.verify(public_key, message, signature)

    def get_algorithm_name(self) -> str:
        return "ECDSA-secp256r1"

    def get_security_level(self) -> str:
        return "128-bit classical | 0-bit quantum (Shor-vulnerable)"


class DilithiumAdapter(SignatureAdapter):
    """
    ML-DSA-44（CRYSTALS-Dilithium2，NIST FIPS 204）适配器。

    后端可用（`dilithium-py` 已安装）时执行**真实**后量子签名；
    否则按 use_fallback 回落 ECDSA，并在 get_security_level() 中**如实标注**回落。
    """

    def __init__(self, use_fallback: bool = True):
        """
        :param use_fallback: 后端缺失时是否回落 ECDSA（False 则直接抛 ImportError）
        """
        self._use_fallback = use_fallback
        if DILITHIUM_AVAILABLE:
            logger.info("[Dilithium] 已加载真实后端 %s", DILITHIUM_BACKEND)
        else:
            if not use_fallback:
                raise ImportError(
                    "Dilithium 不可用且已禁用回落。安装：pip install dilithium-py"
                )
            from blockchain.crypto.ecdsa_utils import ECDSAUtils

            self._fallback = ECDSAUtils
            logger.warning("[Dilithium] 后端缺失，回落 ECDSA（不具备抗量子能力）")

    # -- 属性 ----------------------------------------------------------------
    @property
    def is_quantum_resistant(self) -> bool:
        """是否真正具备抗量子能力（取决于后端是否可用）。"""
        return DILITHIUM_AVAILABLE

    # -- 接口 ----------------------------------------------------------------
    def generate_key_pair(self) -> Tuple[bytes, bytes]:
        """返回 (私钥 sk, 公钥 pk)；回落模式返回 (ECDSA 私钥, ECDSA 公钥)。"""
        if DILITHIUM_AVAILABLE:
            pk, sk = _ML_DSA_44.keygen()
            return sk, pk
        return self._fallback.generate_key_pair()

    def sign(self, private_key, message: bytes) -> bytes:
        if DILITHIUM_AVAILABLE:
            return _ML_DSA_44.sign(private_key, message)
        return self._fallback.sign(private_key, message)

    def verify(self, public_key, message: bytes, signature: bytes) -> bool:
        if DILITHIUM_AVAILABLE:
            try:
                return bool(_ML_DSA_44.verify(public_key, message, signature))
            except Exception as exc:  # 长度/格式非法一律视为验签失败
                logger.debug("[Dilithium] verify 异常，判定为失败: %s", exc)
                return False
        return self._fallback.verify(public_key, message, signature)

    def get_algorithm_name(self) -> str:
        return (
            "ML-DSA-44 (CRYSTALS-Dilithium2)"
            if DILITHIUM_AVAILABLE
            else "ECDSA(Dilithium-fallback)"
        )

    def get_security_level(self) -> str:
        if DILITHIUM_AVAILABLE:
            return "128-bit classical | NIST Level 2 (quantum-resistant)"
        return "0-bit quantum (Shor-vulnerable) — 当前为 ECDSA 回落，未实现后量子"

    def get_migration_readiness(self) -> Dict:
        """迁移就绪度（真实状态，动态查询）。"""
        return {
            "algorithm": self.get_algorithm_name(),
            "standard": "NIST FIPS 204 (ML-DSA)",
            "backend": DILITHIUM_BACKEND,
            "available": DILITHIUM_AVAILABLE,
            "quantum_resistant": DILITHIUM_AVAILABLE,
            "fallback_active": self._use_fallback and not DILITHIUM_AVAILABLE,
            "signature_size_bytes": DILITHIUM_SIGNATURE_SIZE,
            "public_key_size_bytes": DILITHIUM_PUBLIC_KEY_SIZE,
            "private_key_size_bytes": DILITHIUM_PRIVATE_KEY_SIZE,
            "migration_effort": "LOW — 适配器模式，调用方 API 不变",
            "affected_modules": ["SigningService", "ECDSAUtils → DilithiumAdapter"],
        }


class HybridSignatureAdapter:
    """
    混合双签名（迁移期）：ECDSA 保证与既有节点兼容，Dilithium 保证前向抗量子。
    验证策略 AND —— 两者都通过才算通过（纵深防御）。
    """

    def __init__(self):
        self._ecdsa = ECDSAAdapter()
        self._dilithium = DilithiumAdapter(use_fallback=True)

    @property
    def is_hybrid_quantum_resistant(self) -> bool:
        """仅当 Dilithium 后端真实可用时，混合模式才具备抗量子性。"""
        return self._dilithium.is_quantum_resistant

    def hybrid_sign(
        self, ecdsa_private_key, dilithium_private_key, message: bytes
    ) -> Dict[str, bytes]:
        return {
            "ecdsa_signature": self._ecdsa.sign(ecdsa_private_key, message),
            "dilithium_signature": self._dilithium.sign(dilithium_private_key, message),
        }

    def hybrid_verify(
        self,
        ecdsa_public_key,
        dilithium_public_key,
        message: bytes,
        ecdsa_signature: bytes,
        dilithium_signature: bytes,
    ) -> bool:
        ecdsa_ok = self._ecdsa.verify(ecdsa_public_key, message, ecdsa_signature)
        dilithium_ok = self._dilithium.verify(
            dilithium_public_key, message, dilithium_signature
        )
        if not ecdsa_ok:
            logger.warning("[HybridSig] ECDSA 验签失败")
        if not dilithium_ok:
            logger.warning("[HybridSig] Dilithium 验签失败")
        return bool(ecdsa_ok and dilithium_ok)

    def get_transition_status(self) -> Dict:
        return {
            "phase": (
                "Transition (dual-signature)"
                if self.is_hybrid_quantum_resistant
                else "Transition (Dilithium backend missing — ECDSA only)"
            ),
            "ecdsa": self._ecdsa.get_security_level(),
            "dilithium": self._dilithium.get_security_level(),
            "quantum_resistant": self.is_hybrid_quantum_resistant,
            "verification_policy": "AND (both must pass)",
            "total_signature_size_bytes": 70 + DILITHIUM_SIGNATURE_SIZE,
        }


# =============================================================================
# 性能对比（本机实测）
# =============================================================================


def benchmark_signature_adapters(num_iterations: int = 200) -> Dict:
    """实测各适配器的签名/验签耗时（毫秒）与签名长度。后端缺失时不填充估计值。"""
    results: Dict = {"iterations": num_iterations, "adapters": []}
    msg = b"post-quantum benchmark message"

    # ECDSA（实测）
    ecdsa = ECDSAAdapter()
    epriv, epub = ecdsa.generate_key_pair()
    t0 = time.perf_counter()
    for _ in range(num_iterations):
        sig = ecdsa.sign(epriv, msg)
    e_sign = (time.perf_counter() - t0) / num_iterations * 1000
    t0 = time.perf_counter()
    for _ in range(num_iterations):
        ecdsa.verify(epub, msg, sig)
    e_verify = (time.perf_counter() - t0) / num_iterations * 1000
    results["adapters"].append(
        {
            "algorithm": ecdsa.get_algorithm_name(),
            "sign_ms": round(e_sign, 4),
            "verify_ms": round(e_verify, 4),
            "sig_size_bytes": len(sig),
            "quantum_resistant": False,
            "standard": "FIPS 186-5",
            "measured": True,
        }
    )

    # Dilithium / Hybrid（后端可用才实测）
    dil = DilithiumAdapter(use_fallback=True)
    if dil.is_quantum_resistant:
        dpriv, dpub = dil.generate_key_pair()
        t0 = time.perf_counter()
        for _ in range(num_iterations):
            dsig = dil.sign(dpriv, msg)
        d_sign = (time.perf_counter() - t0) / num_iterations * 1000
        t0 = time.perf_counter()
        for _ in range(num_iterations):
            dil.verify(dpub, msg, dsig)
        d_verify = (time.perf_counter() - t0) / num_iterations * 1000
        results["adapters"].append(
            {
                "algorithm": dil.get_algorithm_name(),
                "sign_ms": round(d_sign, 4),
                "verify_ms": round(d_verify, 4),
                "sig_size_bytes": len(dsig),
                "quantum_resistant": True,
                "standard": "FIPS 204",
                "measured": True,
            }
        )
        results["adapters"].append(
            {
                "algorithm": "Hybrid (ECDSA + Dilithium)",
                "sign_ms": round(e_sign + d_sign, 4),
                "verify_ms": round(e_verify + d_verify, 4),
                "sig_size_bytes": len(sig) + len(dsig),
                "quantum_resistant": True,
                "standard": "FIPS 186-5 + FIPS 204",
                "measured": True,
            }
        )
    else:
        results["adapters"].append(
            {
                "algorithm": "ML-DSA-44",
                "measured": False,
                "note": "dilithium-py 未安装，未测量（不填充估计值）",
            }
        )

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print("=" * 62)
    print("Post-Quantum Signature Adapter")
    print("=" * 62)
    print("Dilithium backend:", DILITHIUM_AVAILABLE, "|", DILITHIUM_BACKEND)

    a = DilithiumAdapter()
    print("\nDilithium:", a.get_algorithm_name(), "|", a.get_security_level())
    print("就绪度:", a.get_migration_readiness())

    print("\n混合模式:", HybridSignatureAdapter().get_transition_status())

    print("\n性能对比（本机实测）:")
    for row in benchmark_signature_adapters(100)["adapters"]:
        print("   ", row)

"""
ECDSA工具类 - MARL-ECDSA共识链密码学核心
基于 NIST secp256r1 (P-256) 椭圆曲线
遵循 FIPS 186-5 标准 + RFC 6979 确定性k值生成
"""
import hashlib
import json
import logging
import os
import time
from typing import Tuple, Optional, Dict, Any

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature, encode_dss_signature
)

logger = logging.getLogger(__name__)
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.exceptions import InvalidSignature


# =============================================================================
# 私钥落盘口令（BUG3 修复：私钥不再明文存储）
#
# ⚠️ 09-28 修正（全检 #4）：下列原先的描述会造成**虚假安全感**，务必读全。
#
# 原实现的两个问题：
#   1) DEFAULT_KEY_PASSPHRASE 是**随源码分发的公开常量** —— 用它加密的私钥，
#      任何拿到仓库的人都能打开（09-28 实测：keys/ 下 5 个"已加密"私钥全部
#      可用该默认口令成功解出）。因此"私钥已加密存储"**不等于**"私钥受到保护"。
#   2) 回退是**静默**的：环境变量缺失时既不报错也不告警，而调用方日志照样打印
#      "私钥已加密存储"，形成"说了没做"的闭环。
#
# 现在的语义：
#   - 环境变量 MARL_ECDSA_KEY_PASSPHRASE 优先（生产/演示必须设置）；
#   - 缺失时**仍回退**（避免一次性打断既有本地演示与复现流程），但每次都打印
#     WARNING，明确指出该口令是公开的、不构成任何保密性；
#   - 设置 MARL_ECDSA_REQUIRE_KEY_PASSPHRASE=1 进入严格模式：缺失即抛
#     KeyPassphraseError。**对外演示/准生产建议开启**。
# =============================================================================
DEFAULT_KEY_PASSPHRASE = b"NON_PRODUCTION_ONLY_insecure_default_change_me"  # 公开常量：不构成保密性
#: 严格模式开关：置为 1/true/yes/on 时，口令缺失直接抛错而非回退默认
REQUIRE_PASSPHRASE_ENV = "MARL_ECDSA_REQUIRE_KEY_PASSPHRASE"


class KeyPassphraseError(RuntimeError):
    """严格模式下未提供私钥落盘口令。"""


def _strict_mode() -> bool:
    return os.environ.get(REQUIRE_PASSPHRASE_ENV, "").strip().lower() in (
        "1", "true", "yes", "on"
    )


def resolve_key_passphrase() -> bytes:
    """解析私钥口令：环境变量优先，缺失时行为由严格模式开关决定。

    :raises KeyPassphraseError: 严格模式下环境变量未提供。
    """
    env = os.environ.get("MARL_ECDSA_KEY_PASSPHRASE")
    if env:
        return env.encode("utf-8")

    if _strict_mode():
        raise KeyPassphraseError(
            f"未提供私钥落盘口令：请设置环境变量 MARL_ECDSA_KEY_PASSPHRASE。"
            f"（当前 {REQUIRE_PASSPHRASE_ENV} 已开启严格模式，拒绝回退到随源码"
            f"公开的 DEFAULT_KEY_PASSPHRASE —— 该常量对所有读到此仓库的人可见，"
            f"用它加密等同于明文。）"
        )

    logger.warning(
        "[ECDSA] 环境变量 MARL_ECDSA_KEY_PASSPHRASE 未设置，正回退到随源码公开的 "
        "DEFAULT_KEY_PASSPHRASE。用它加密的私钥**不具备任何保密性**（任何拿到本"
        f"仓库的人均可解密）。演示/生产请设置环境变量，或设置 "
        f"{REQUIRE_PASSPHRASE_ENV}=1 改为提供缺失即报错。"
    )
    return DEFAULT_KEY_PASSPHRASE


class ECDSAUtils:
    """
    ECDSA工具类：封装完整的签名/验签流程
    - 密钥对生成（secp256r1）
    - 消息签名（SHA256+ECDSA，RFC 6979确定性k值由底层库保证）
    - 签名验证
    - 公私钥序列化/反序列化
    - DER格式签名解析（提取r,s值用于k值重用检测）
    """

    CURVE = ec.SECP256R1()

    # -------------------------------------------------------------------------
    # 密钥管理
    # -------------------------------------------------------------------------

    @staticmethod
    def generate_key_pair() -> Tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey]:
        """
        生成 secp256r1 密钥对
        :return: (private_key, public_key)
        """
        private_key = ec.generate_private_key(ECDSAUtils.CURVE)
        public_key = private_key.public_key()
        return private_key, public_key

    @staticmethod
    def private_key_to_bytes(
        private_key: ec.EllipticCurvePrivateKey,
        passphrase: Optional[bytes] = None,
    ) -> bytes:
        """
        私钥序列化为 PEM 字节。
        BUG3 修复：传入 passphrase 时使用 BestAvailableEncryption 加密落盘；
        未传（默认 None）时退回 NoEncryption，以保持对直接调用方/旧测试的兼容。
        """
        enc_algo = (
            serialization.NoEncryption()
            if passphrase is None
            else serialization.BestAvailableEncryption(passphrase)
        )
        return private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=enc_algo,
        )

    @staticmethod
    def public_key_to_bytes(public_key: ec.EllipticCurvePublicKey) -> bytes:
        """公钥序列化为 PEM 字节"""
        return public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

    @staticmethod
    def public_key_to_hex(public_key: ec.EllipticCurvePublicKey) -> str:
        """公钥序列化为十六进制字符串（用于链上存储）"""
        raw = public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint
        )
        return raw.hex()

    @staticmethod
    def private_key_from_bytes(
        pem_bytes: bytes,
        passphrase: Optional[bytes] = None,
    ) -> ec.EllipticCurvePrivateKey:
        """
        从 PEM 字节反序列化私钥。
        BUG3 修复：先用传入 passphrase 尝试解密加载（加密 PEM）；
        失败则回退 NoEncryption 加载旧明文 PEM 并打 warning（向后兼容已存在的 keys/）。
        """
        try:
            return serialization.load_pem_private_key(pem_bytes, password=passphrase)
        except Exception:
            # 兼容旧版明文 PEM（NoEncryption）：先警告再回退
            logger.warning(
                "[ECDSAUtils] 用口令加载私钥失败，回退尝试无加密(旧明文PEM)加载"
            )
            return serialization.load_pem_private_key(pem_bytes, password=None)

    @staticmethod
    def public_key_from_bytes(pem_bytes: bytes) -> ec.EllipticCurvePublicKey:
        """从 PEM 字节反序列化公钥"""
        return serialization.load_pem_public_key(pem_bytes)

    @staticmethod
    def public_key_from_hex(hex_str: str) -> ec.EllipticCurvePublicKey:
        """从十六进制字符串反序列化公钥"""
        raw = bytes.fromhex(hex_str)
        return ec.EllipticCurvePublicKey.from_encoded_point(ECDSAUtils.CURVE, raw)

    # -------------------------------------------------------------------------
    # 消息构造与哈希
    # -------------------------------------------------------------------------

    @staticmethod
    def build_message(
        agent_id: str,
        action: Any,
        timestamp: int,
        nonce: int,
        extra: Optional[Dict] = None
    ) -> bytes:
        """
        构造待签名消息体
        格式: {agent_id, action_hash, timestamp, nonce, [extra]}
        :return: UTF-8编码的JSON字节串（稳定排序）
        """
        action_hash = hashlib.sha256(
            json.dumps(action, sort_keys=True, ensure_ascii=False).encode('utf-8')
        ).hexdigest()

        payload = {
            'agent_id': agent_id,
            'action_hash': action_hash,
            'timestamp': timestamp,
            'nonce': nonce,
        }
        if extra:
            payload.update(extra)

        return json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8')

    @staticmethod
    def hash_message(message: bytes) -> bytes:
        """对消息计算 SHA-256 摘要"""
        return hashlib.sha256(message).digest()

    # -------------------------------------------------------------------------
    # 签名与验签
    # -------------------------------------------------------------------------

    @staticmethod
    def sign(
        private_key: ec.EllipticCurvePrivateKey,
        message: bytes
    ) -> bytes:
        """
        使用私钥对消息进行 ECDSA 签名（SHA-256哈希）
        使用 RFC 6979 确定性 k 值生成（deterministic_signing），防止 k 值重用
        :param private_key: 签名私钥
        :param message: 原始消息字节
        :return: DER 格式签名字节
        """
        # P1-12修复: 显式启用 RFC 6979 确定性 nonce，同一私钥+同一消息必须产生相同签名
        # （deterministic_signing 参数口径以实测为准：requirements.txt 下界 cryptography>=43，
        #   交付运行库锁定 46.0.7——勿引用未经验证的旧版本号）
        signature = private_key.sign(
            message,
            ec.ECDSA(hashes.SHA256(), deterministic_signing=True),
        )
        return signature

    @staticmethod
    def _payload_equivalent(expected: bytes, actual: bytes) -> bool:
        """字节不等时的语义等价判定：只容忍 JSON 数值写法差异。

        为什么要这一步：`build_message` 用 json.dumps 重建，调用方把时间戳
        传成 float（1000.0，同值）时重建结果写作 1000.0，与被签的 1000 字节
        不等 —— 但字段值完全一致，不该判成篡改。反过来字符串 "1000" 与整数
        1000 在 dict 比较里不相等，仍然拒绝（否则类型混淆可绕过绑定）。

        放宽的只是「表示形式」，不是「字段集合」：expected 由包内字段（含
        extra）重建，字典相等即意味着键集合相等 —— 签名体里多出来的、未被
        包声明的键一律不等，按篡改拒绝。
        """
        try:
            return json.loads(expected) == json.loads(actual)
        except Exception:
            return False

    @staticmethod
    def verify(
        public_key: ec.EllipticCurvePublicKey,
        message: bytes,
        signature: bytes
    ) -> bool:
        """
        使用公钥验证 ECDSA 签名
        :return: True=验签通过，False=验签失败（消息被篡改/非法签名）
        """
        try:
            public_key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
            return True
        except InvalidSignature:
            return False
        except Exception as e:
            logger.debug(f"ECDSA验签异常: {e}")
            return False
    # -------------------------------------------------------------------------

    @staticmethod
    def extract_rs(signature: bytes) -> Tuple[int, int]:
        """
        从 DER 格式签名中提取 (r, s) 值
        用于 k 值重用检测（相同的 r 值意味着使用了相同的 k）
        """
        r, s = decode_dss_signature(signature)
        return r, s

    @staticmethod
    def encode_rs(r: int, s: int) -> bytes:
        """将 (r, s) 值编码为 DER 格式签名"""
        return encode_dss_signature(r, s)

    # -------------------------------------------------------------------------
    # 完整签名流程（含消息构造）
    # -------------------------------------------------------------------------

    @staticmethod
    def sign_action(
        agent_id: str,
        private_key: ec.EllipticCurvePrivateKey,
        action: Any,
        nonce: int,
        timestamp: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        为智能体行为生成完整的签名包
        :return: 包含 message_bytes, signature_hex, timestamp, nonce 的字典
        """
        if timestamp is None:
            timestamp = int(time.time() * 1000)  # 毫秒时间戳

        message = ECDSAUtils.build_message(agent_id, action, timestamp, nonce)
        signature = ECDSAUtils.sign(private_key, message)
        r, s = ECDSAUtils.extract_rs(signature)

        return {
            'agent_id': agent_id,
            'action': action,
            'timestamp': timestamp,
            'nonce': nonce,
            'message_hex': message.hex(),
            'signature_hex': signature.hex(),
            'r': r,
            's': s,
        }

    @staticmethod
    def verify_action_package(
        package: Dict[str, Any],
        public_key: ec.EllipticCurvePublicKey
    ) -> bool:
        """
        验证智能体行为签名包
        :param package: sign_action() 返回的签名包
        :param public_key: 发送方的公钥
        :return: True=合法，False=非法
        """
        try:
            message = bytes.fromhex(package['message_hex'])
            signature = bytes.fromhex(package['signature_hex'])

            # 安全加固（2026-10-15）：校验「签名承诺的业务字段」与「包内明文字段」
            # 是否一致。
            # 原实现只校验 (message_hex, signature_hex) 这一对，二者自洽即通过，
            # 导致攻击者可篡改 action / nonce / timestamp 明文而保留原签名，
            # 验签仍然通过（业务字段与签名承诺脱钩）。此处用包内明文重新构造
            # message 并与 message_hex 逐位比对，不一致即拒绝。
            # 载荷绑定（fail-closed）：四个承诺字段缺一不可。
            #
            # 为什么要显式判缺：曾有一版写成「package 带全字段才比对」，于是
            # 把 agent_id/action/timestamp/nonce 删掉、只留 message_hex +
            # signature_hex，绑定检查就被整段跳过 —— 而
            # cooperation_detector.filter_verified_packages() 吃的正是**外部
            # 传入**的包。删字段即绕过，这是后门不是兼容。
            missing = [
                k for k in ('agent_id', 'action', 'timestamp', 'nonce')
                if k not in package
            ]
            if missing:
                logger.warning(
                    "[ECDSAUtils] 签名包缺少载荷绑定所需字段 "
                    f"{missing}，拒绝（裸 message_hex + signature_hex "
                    "无法证明签名与业务字段相关）"
                )
                return False

            expected = ECDSAUtils.build_message(
                package['agent_id'],
                package['action'],
                package['timestamp'],
                package['nonce'],
                package.get('extra'),
            )
            if expected != message and not ECDSAUtils._payload_equivalent(
                expected, message
            ):
                logger.debug(
                    "[ECDSAUtils] 签名包业务字段与签名承诺不一致，拒绝 "
                    f"(agent={package.get('agent_id')})"
                )
                return False

            return ECDSAUtils.verify(public_key, message, signature)
        except Exception as e:
            logger.debug(f"ECDSA验签异常: {e}")
            return False

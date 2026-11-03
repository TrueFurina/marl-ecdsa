"""
ECDSA 签名服务 — 从 BlockchainMARLBridge 拆分出的子组件（P2-D）
职责：ECDSA 签名 + SecurityGuard 校验 + nonce 管理 + 验签统计
扩展（2026-10-15）：可选后量子混合签名后端（signature_backend="hybrid"），
      接入真实 ML-DSA-44（CRYSTALS-Dilithium，FIPS 204）作为迁移期纵深防御。
      默认仍为纯 ECDSA（不接主链路），仅当显式选择 hybrid 才启用量子签名。
"""
import base64
import logging
from typing import Dict, Optional, Any, Tuple

from blockchain.crypto.ecdsa_utils import ECDSAUtils
import blockchain.crypto.dilithium_adapter as _dilithium_module
from blockchain.crypto.dilithium_adapter import (
    DilithiumAdapter,
    HybridSignatureAdapter,
)

logger = logging.getLogger(__name__)

# signature_backend 合法值域（契约，2026-10-19 收紧）
# 收紧动机：原实现对任何非 "hybrid" 的值都静默走纯 ECDSA 路径——
# 调用方若把 "hybrid" 拼错（如 "hydrid"/"HYBRID"/" hybrid "），
# 会拿到一个「自认为已启用后量子双签名、实际只有 ECDSA」的服务，
# 属于 fail-open 式契约违反（与 L56-61「hybrid 不可用即抛错」的精神相悖）。
# 现改为白名单严格匹配：非法值构造期即 ValueError，绝不让误配置活到运行时。
VALID_SIGNATURE_BACKENDS = ("ecdsa", "hybrid")


class SigningService:
    """
    ECDSA 签名与安全校验服务

    封装完整签名流水线：
    1. ECDSA sign_action() — 每步行为签名
    2. SecurityGuard check_package() — 签名包安全校验
    3. nonce 严格递增管理（防重放）
    4. 回合级验签 verify_episode_transactions()
    """

    def __init__(
        self,
        key_manager=None,
        security_guard=None,
        n_agents: int = 3,
        state_path: Optional[str] = None,
        signature_backend: str = "ecdsa",
    ):
        self.key_manager = key_manager
        self.security_guard = security_guard

        # ── 后量子混合签名后端（opt-in，默认纯 ECDSA，不接主链路）──
        # "ecdsa"  : 经典签名，与既有节点完全兼容（默认，行为不变）
        # "hybrid" : 真实 ML-DSA-44（CRYSTALS-Dilithium2, FIPS 204）双签名纵深防御
        # 诚实约束：若显式选择 hybrid 但后端不可用，直接 fail-closed 抛错，
        #           绝不静默回落 ECDSA 冒充「抗量子」。
        self._signature_backend = signature_backend
        if signature_backend not in VALID_SIGNATURE_BACKENDS:
            raise ValueError(
                f"[SigningService] 非法 signature_backend={signature_backend!r}；"
                f"仅接受 {VALID_SIGNATURE_BACKENDS}。为避免拼写错误/误配置导致"
                f"静默回落纯 ECDSA（调用方误以为已启用后量子签名），此处 fail-closed。"
            )
        self._hybrid: Optional[HybridSignatureAdapter] = None
        self._dil_adapter: Optional[DilithiumAdapter] = None
        # 每个智能体的 Dilithium 密钥对缓存（sk, pk），仅 hybrid 模式使用，
        # 与 ECDSA KeyManager 互不耦合，公钥随签名包携带以便对端独立验签。
        self._dilithium_keys: Dict[str, Tuple[bytes, bytes]] = {}
        if signature_backend == "hybrid":
            if not _dilithium_module.DILITHIUM_AVAILABLE:
                raise RuntimeError(
                    "[SigningService] 已请求 hybrid 后量子签名，但 Dilithium 后端"
                    "（dilithium-py / ML-DSA-44）不可用；为避免静默冒充抗量子，"
                    "已 fail-closed。请先安装后端：pip install dilithium-py"
                )
            self._hybrid = HybridSignatureAdapter()
            self._dil_adapter = DilithiumAdapter(use_fallback=False)
            logger.info(
                "[SigningService] hybrid 后量子签名已启用（ECDSA + ML-DSA-44, AND 策略）"
            )

        # nonce 计数器（每个智能体独立递增，防重放）
        self._nonce_counters: Dict[str, int] = {f"agent_{i}": 0 for i in range(n_agents)}

        # 签名/验签/安全统计
        self._sign_count = 0
        self._verify_count = 0
        self._security_pass_count = 0
        self._security_fail_count = 0

        # P0-2 修复：初始化时同步 nonce 基线到 SecurityGuard
        if self.security_guard is not None:
            agent_ids_list = [f"agent_{i}" for i in range(n_agents)]
            for aid in agent_ids_list:
                self.security_guard.register_nonce_baseline(aid, 0)
            logger.info(f"[SigningService] nonce基线已同步到SecurityGuard: {agent_ids_list}")

        # P1-17 修复：若提供 state_path 且文件存在，则从统一快照恢复
        # （nonce_counters 与 security_guard 状态同源，避免重启后自伤式 DoS）
        if state_path is not None:
            self.load_state(state_path)

    def sign_and_verify(
        self,
        agent_id: str,
        action_data: Any,
        nonce: int,
        timestamp: int,
    ) -> Optional[Dict]:
        """
        签名 + 安全校验一体化流程

        :param agent_id: 智能体 ID
        :param action_data: 动作数据
        :param nonce: 递增 nonce（由调用方提供）
        :param timestamp: 毫秒级时间戳
        :return: signed_package dict（含 verified 标记），或 None（签名失败）
        """
        signed_package = None

        # ── 1. ECDSA 签名 ──
        if self.key_manager is not None:
            priv_key = self.key_manager.get_private_key(agent_id)
            if priv_key is not None:
                try:
                    signed_package = ECDSAUtils.sign_action(
                        agent_id=agent_id,
                        private_key=priv_key,
                        action=action_data,
                        nonce=nonce,
                        timestamp=timestamp,
                    )
                    self._sign_count += 1
                    logger.debug(
                        f"[SigningService] ECDSA签名完成: {agent_id} nonce={nonce}"
                    )
                except Exception as e:
                    logger.warning(f"[SigningService] ECDSA签名失败 {agent_id}: {e}")
                    return None

        # ── 1b. 后量子 Dilithium 双签名（仅 hybrid 模式，AND 纵深防御）──
        # 诚实约束：对与 ECDSA 完全相同的规范消息字节签名，公钥随包携带，
        # 对端无需密钥仓库即可独立验签（与 ECDSA 的 message_hex 自包含一致）。
        # 绝不修改任何既有 ECDSA 字段 —— 仅「追加」Dilithium 字段。
        if signed_package is not None and self._signature_backend == "hybrid":
            try:
                sk, pk = self._ensure_dilithium_keypair(agent_id)
                message_bytes = bytes.fromhex(signed_package['message_hex'])
                dil_sig = self._dil_adapter.sign(sk, message_bytes)
                signed_package['dilithium_signature_hex'] = dil_sig.hex()
                signed_package['dilithium_pubkey_hex'] = pk.hex()
                signed_package['signature_backend'] = 'hybrid'
                logger.debug(
                    f"[SigningService] Dilithium双签名完成: {agent_id} nonce={nonce}"
                )
            except Exception as e:
                logger.warning(f"[SigningService] Dilithium双签名失败 {agent_id}: {e}")
                return None

        # ── 2. SecurityGuard 校验 ──
        if signed_package is not None and self.security_guard is not None:
            try:
                is_safe, reason = self.security_guard.check_package(signed_package)
                if is_safe:
                    self._security_pass_count += 1
                    signed_package['verified'] = True
                    logger.debug(f"[SigningService] SecurityGuard通过: {agent_id}")
                else:
                    self._security_fail_count += 1
                    signed_package['verified'] = False
                    logger.warning(
                        f"[SigningService] SecurityGuard拦截 {agent_id}: {reason}"
                    )
            except Exception as e:
                logger.warning(f"[SigningService] SecurityGuard校验异常 {agent_id}: {e}")
                signed_package['verified'] = False

        return signed_package

    def _ensure_dilithium_keypair(self, agent_id: str) -> Tuple[bytes, bytes]:
        """
        获取（按需生成并缓存）某智能体的 Dilithium 密钥对 (sk, pk)。
        仅 hybrid 模式调用；密钥不落盘，仅在服务实例内存中稳定复用，
        保证同一实例对同一 agent 多次签名为同一密钥（与真实节点单密钥一致）。
        """
        if agent_id not in self._dilithium_keys:
            adapter = DilithiumAdapter(use_fallback=False)
            sk, pk = adapter.generate_key_pair()
            self._dilithium_keys[agent_id] = (sk, pk)
            logger.info(
                f"[SigningService] 已为 {agent_id} 生成 Dilithium 密钥对"
                f"（公钥 {len(pk)} 字节）"
            )
        return self._dilithium_keys[agent_id]

    def verify_signed_package(self, package: Dict, ecdsa_pubkey) -> bool:
        """
        统一验签：依据本服务配置的 signature_backend 执行对应策略。
        - ecdsa 模式：仅 ECDSA 验签（向后兼容，纯 ECDSA 包即通过）。
        - hybrid 模式：ECDSA 与 Dilithium 双重 AND 验签；
          **若包中缺失 Dilithium 字段，视为降级攻击，直接拒绝**（fail-closed），
          绝不把 ECDSA-only 包当 hybrid 通过。

        :param package: sign_and_verify() 返回的签名包（hybrid 时含 dilithium 字段）
        :param ecdsa_pubkey: 发送方 ECDSA 公钥
        :return: 验签是否通过
        """
        ecdsa_ok = ECDSAUtils.verify_action_package(package, ecdsa_pubkey)
        if not ecdsa_ok:
            return False

        # hybrid 模式：强制要求 Dilithium 双签名（AND），缺失即拒绝
        if self._signature_backend == "hybrid":
            if ('dilithium_signature_hex' not in package
                    or 'dilithium_pubkey_hex' not in package):
                logger.warning(
                    "[SigningService] hybrid 策略下收到无 Dilithium 字段的包，"
                    "判定为降级攻击并拒绝"
                )
                return False
            try:
                d_pub = bytes.fromhex(package['dilithium_pubkey_hex'])
                d_sig = bytes.fromhex(package['dilithium_signature_hex'])
                message_bytes = bytes.fromhex(package['message_hex'])
                # use_fallback=False：后端缺失时直接失败，绝不冒充抗量子
                adapter = DilithiumAdapter(use_fallback=False)
                dil_ok = adapter.verify(d_pub, message_bytes, d_sig)
            except Exception as e:
                logger.warning(f"[SigningService] Dilithium验签异常: {e}")
                dil_ok = False
            if not dil_ok:
                logger.warning("[SigningService] 混合验签 Dilithium 部分失败")
            return bool(ecdsa_ok and dil_ok)

        # ecdsa 模式：ECDSA 通过即通过
        return True

    def verify_episode_transactions(self, bc_node) -> None:
        """
        验签：验证交易池中所有交易的签名完整性。
        默认（ecdsa）仅做 ECDSA 验签；hybrid 模式下额外对 Dilithium 部分
        取 AND 验签（包内携带 Dilithium 公钥与签名，无需额外密钥仓库），
        缺失 Dilithium 字段的包将被拒绝（防降级）。
        """
        if bc_node is None or self.key_manager is None:
            return

        pending_txs = bc_node.get_pending_transactions()
        for tx in pending_txs:
            if not tx.signature_hex:
                continue

            pub_key = self.key_manager.get_public_key(tx.agent_id)
            if pub_key is None:
                continue

            # 从 Transaction.extra 中恢复签名包
            package = {
                'agent_id': tx.agent_id,
                'action': tx.action,
                'timestamp': tx.timestamp,
                'nonce': tx.nonce,
                'message_hex': tx.extra.get('message_hex', ''),
                'signature_hex': tx.signature_hex,
                'r': tx.extra.get('r'),
                's': tx.extra.get('s'),
            }
            # hybrid 模式：从 extra 还原 Dilithium 字段（前向兼容）。
            # 注意：若 extra 中缺失 Dilithium 字段，package 不会带上该字段，
            # 下游 verify_signed_package 在 hybrid 模式下会直接拒绝（fail-closed），
            # 绝不把 ECDSA-only 包当 hybrid 通过（见 L199-203）。
            if self._signature_backend == "hybrid":
                d_sig = tx.extra.get('dilithium_signature_hex')
                d_pub = tx.extra.get('dilithium_pubkey_hex')
                if d_sig is not None and d_pub is not None:
                    package['dilithium_signature_hex'] = d_sig
                    package['dilithium_pubkey_hex'] = d_pub

            try:
                is_valid = self.verify_signed_package(package, pub_key)
                self._verify_count += 1
                if is_valid:
                    # F02（2026-11-02 赛后）：验签结果传递给链准入——此前本方法
                    # 只计数/打日志、从不写 extra['verified']，导致 _validate_new_block
                    # 的 verified 门恒拒（被旧无条件结算掩盖）。认证自此真实决定上链。
                    tx.extra['verified'] = True
                    logger.debug(
                        f"[SigningService] 验签通过: {tx.agent_id} tx={tx.tx_id[:8]}"
                    )
                else:
                    tx.extra['verified'] = False
                    logger.warning(
                        f"[SigningService] 验签失败: {tx.agent_id} tx={tx.tx_id[:8]}"
                    )
            except Exception as e:
                logger.warning(f"[SigningService] 验签异常 {tx.agent_id}: {e}")
                self._verify_count += 1

    # -------------------------------------------------------------------------
    # 持久化（P1-17 修复：统一快照，签名服务与守卫必须同源写入/读取）
    # -------------------------------------------------------------------------

    def save_state(self, path: str) -> None:
        """
        持久化「签名服务 + 安全守卫」的统一快照到单个文件。
        关键：nonce_counters（发号机）与 security_guard 状态写入【同一份文件】，
        重启后由 load_state 同源读回，两者永远一致，不会把合法 nonce 误判为重放。
        """
        import json
        if self.security_guard is None:
            snap = {'nonce_counters': dict(self._nonce_counters), 'guard': None}
        else:
            snap = {
                'nonce_counters': dict(self._nonce_counters),
                'guard': self.security_guard.to_snapshot(),
            }
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(snap, f)
            logger.info(f"[SigningService] 状态快照已保存: {path}")
        except Exception as e:
            logger.warning(f"[SigningService] 状态快照保存失败: {e}")

    def load_state(self, path: str) -> None:
        """
        从统一快照恢复（P1-17 修复）。
        恢复后用 register_nonce_baseline 重新同步守卫的 nonce 基线，
        作为双重保险，确保守卫与发号机计数一致（杜绝自伤式 DoS）。
        """
        import json
        import os
        if not os.path.exists(path):
            logger.info(f"[SigningService] 快照不存在，启动全新状态: {path}")
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                snap = json.load(f)
        except Exception as e:
            logger.warning(f"[SigningService] 快照读取失败，启动全新状态: {e}")
            return
        self._nonce_counters = dict(snap.get('nonce_counters', self._nonce_counters))
        guard_snap = snap.get('guard')
        if self.security_guard is not None and guard_snap is not None:
            # 守卫已从同源快照恢复，nonce 基线自然一致，无需重复注册
            self.security_guard.from_snapshot(guard_snap)
        elif self.security_guard is not None:
            # 仅当快照未含守卫状态时，才用计数器重建基线
            for aid, cnt in self._nonce_counters.items():
                self.security_guard.register_nonce_baseline(aid, cnt)

    def reset_nonce_state(self) -> None:
        """
        重置 nonce 状态（nonce_counters + SecurityGuard nonce_registry 同步清空）
        """
        agent_ids_list = list(self._nonce_counters.keys())
        for aid in agent_ids_list:
            self._nonce_counters[aid] = 0
        if self.security_guard is not None:
            self.security_guard.reset_all_nonces(agent_ids_list)
            for aid in agent_ids_list:
                self.security_guard.register_nonce_baseline(aid, 0)
        logger.info(f"[SigningService] nonce状态已完全重置: {agent_ids_list}")

    def get_stats(self) -> Dict:
        """获取签名/验签/安全统计"""
        return {
            'signature_backend': self._signature_backend,
            'ecdsa_sign_count': self._sign_count,
            'ecdsa_verify_count': self._verify_count,
            'security_pass_count': self._security_pass_count,
            'security_fail_count': self._security_fail_count,
            'dilithium_keypairs': len(self._dilithium_keys),
        }

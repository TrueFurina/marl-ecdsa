"""
ECDSA 签名服务 — 从 BlockchainMARLBridge 拆分出的子组件（P2-D）
职责：ECDSA 签名 + SecurityGuard 校验 + nonce 管理 + 验签统计
"""
import logging
from typing import Dict, Optional, Any

from blockchain.crypto.ecdsa_utils import ECDSAUtils

logger = logging.getLogger(__name__)


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
    ):
        self.key_manager = key_manager
        self.security_guard = security_guard

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

    def verify_episode_transactions(self, bc_node) -> None:
        """
        ECDSA 验签：验证交易池中所有交易的签名完整性
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

            try:
                is_valid = ECDSAUtils.verify_action_package(package, pub_key)
                self._verify_count += 1
                if is_valid:
                    logger.debug(
                        f"[SigningService] ECDSA验签通过: {tx.agent_id} tx={tx.tx_id[:8]}"
                    )
                else:
                    logger.warning(
                        f"[SigningService] ECDSA验签失败: {tx.agent_id} tx={tx.tx_id[:8]}"
                    )
            except Exception as e:
                logger.warning(f"[SigningService] ECDSA验签异常 {tx.agent_id}: {e}")
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
            'ecdsa_sign_count': self._sign_count,
            'ecdsa_verify_count': self._verify_count,
            'security_pass_count': self._security_pass_count,
            'security_fail_count': self._security_fail_count,
        }

"""
行为记录服务 — 从 BlockchainMARLBridge 拆分出的子组件（P2-D）
职责：行为缓冲 → Transaction 转换 → 批量上链
"""
import hashlib
import json
import logging
from typing import Dict, List, Optional

from blockchain.ledger.block import Transaction

logger = logging.getLogger(__name__)


class ActionRecorder:
    """
    行为记录与上链服务

    封装完整行为记录流水线：
    1. record_action() — 每步行为缓冲（含签名信息）
    2. batch_upload() — 每 N 步批量转为 Transaction 加入交易池
    3. flush_pending() — 回合结束时刷新剩余行为
    4. pending_to_transaction() — 行为字典 → Transaction 数据结构
    """

    UPLOAD_INTERVAL = 10  # 默认每10步批量上链一次

    def __init__(
        self,
        bc_node=None,
        n_agents: int = 3,
        upload_interval: int = 10,
    ):
        self.bc_node = bc_node
        self.UPLOAD_INTERVAL = upload_interval
        self._pending_actions: List[Dict] = []
        self._tx_count = 0

    def record_action(
        self,
        agent_id: str,
        step: int,
        action_data,
        env_reward: float,
        timestamp: int,
        nonce: int,
        signed_package: Optional[Dict] = None,
    ) -> None:
        """
        记录单步行为到缓冲区

        :param agent_id: 智能体 ID
        :param step: 当前步数
        :param action_data: 动作数据
        :param env_reward: 环境奖励
        :param timestamp: 毫秒级时间戳
        :param nonce: 当前 nonce
        :param signed_package: ECDSA 签名包（可选）
        """
        action_hash = hashlib.sha256(
            json.dumps(str(action_data)).encode()
        ).hexdigest()[:16]

        pending = {
            'agent_id': agent_id,
            'step': step,
            'action': action_data,
            'action_hash': action_hash,
            'env_reward': float(env_reward),
            'timestamp': timestamp,
            'nonce': nonce,
        }

        # 附加签名信息（如有）
        if signed_package is not None:
            pending['signature_hex'] = signed_package['signature_hex']
            pending['message_hex'] = signed_package['message_hex']
            pending['r'] = signed_package['r']
            pending['s'] = signed_package['s']
            # P0-5: 仅当 signed_package 明确包含 'verified' 字段时才设置
            # 无 'verified' 字段 = 签名成功但未做 SecurityGuard 检查，视为可信
            if 'verified' in signed_package:
                pending['verified'] = signed_package['verified']

                # P0-5: 拒绝 verified=False 的行为进入缓冲区
                # 仅当 'verified' 字段明确存在于 signed_package 且值为 False 时才拒绝
                if signed_package['verified'] is False:
                    logger.warning(
                        f"[ActionRecorder] 拒绝未验证行为: agent={agent_id} "
                        f"step={step} nonce={nonce} — verified=False"
                    )
                    return  # 不缓冲该行为

        self._pending_actions.append(pending)

    def batch_upload(self) -> None:
        """
        批量上链：将行为缓冲转为 Transaction，加入区块链交易池
        仅记录行为存证，不触发激励结算
        P0-5: 仅上传 verified=True 的行为
        """
        if not self._pending_actions:
            return

        # P0-5: 过滤未验证行为，仅上传 verified=True
        # 注意：没有 'verified' 字段的行为（无签名包）默认允许，保持向后兼容
        verified_actions = [
            p for p in self._pending_actions
            if p.get('verified', True)  # 无 verified 字段视为可信（无签名包场景）
        ]
        unverified_count = len(self._pending_actions) - len(verified_actions)
        if unverified_count > 0:
            logger.debug(
                f"[ActionRecorder] 过滤 {unverified_count} 条未验证行为"
            )

        if self.bc_node is not None:
            for pending in verified_actions:
                tx = self.pending_to_transaction(pending)
                if tx is not None:
                    self.bc_node.add_transaction(tx)
                    self._tx_count += 1
            n = len(verified_actions)
            logger.debug(
                f"[ActionRecorder] 批量上链 {n} 条行为记录 → Transaction（仅存证，未结算）"
            )
        else:
            n = len(verified_actions)
            logger.debug(f"[ActionRecorder] 批量上链 {n} 条行为记录（stub模式）")

        self._pending_actions.clear()

    def flush_pending(self) -> None:
        """
        回合结束时刷新剩余行为缓冲到交易池
        P0-5: 仅刷新 verified=True 的行为
        """
        if self.bc_node is not None and self._pending_actions:
            # P0-5: 过滤未验证行为
            verified_actions = [
                p for p in self._pending_actions
                if p.get('verified', True)  # 无 verified 字段视为可信（无签名包场景）
            ]
            unverified_count = len(self._pending_actions) - len(verified_actions)
            if unverified_count > 0:
                logger.debug(
                    f"[ActionRecorder] flush过滤 {unverified_count} 条未验证行为"
                )
            for pending in verified_actions:
                tx = self.pending_to_transaction(pending)
                if tx is not None:
                    self.bc_node.add_transaction(tx)
                    self._tx_count += 1
            self._pending_actions.clear()
            logger.debug("[ActionRecorder] 刷新剩余行为到交易池")

    def pending_to_transaction(self, pending: Dict) -> Optional[Transaction]:
        """将行为缓冲记录转为 Transaction 数据结构"""
        try:
            tx = Transaction(
                tx_id="",  # 占位，后续计算
                agent_id=pending['agent_id'],
                action=pending.get('action', pending.get('action_hash')),
                action_hash=pending['action_hash'],
                timestamp=pending['timestamp'],
                nonce=pending.get('nonce', 0),
                signature_hex=pending.get('signature_hex', ''),
                tx_type="action",
                extra={
                    'step': pending.get('step', 0),
                    'env_reward': pending.get('env_reward', 0.0),
                    'verified': pending.get('verified', False),  # P0-5: 无 verified 字段表示未做安全检查
                    'r': pending.get('r'),
                    's': pending.get('s'),
                    'message_hex': pending.get('message_hex', ''),
                },
            )
            tx.tx_id = tx.compute_hash()
            return tx
        except Exception as e:
            logger.warning(f"[ActionRecorder] Transaction创建失败: {e}")
            return None

    def get_stats(self) -> Dict:
        """获取行为记录统计"""
        return {
            'pending_actions': len(self._pending_actions),
            'tx_count': self._tx_count,
        }

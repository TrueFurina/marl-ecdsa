"""
惩罚智能合约
对恶意行为实施分级惩罚，调用身份合约更新状态
"""
import logging
from typing import Dict, Optional
from ..ledger.world_state import WorldState, AgentStatus
from ..config_loader import load_penalty_thresholds
from .identity_contract import ContractCaller

logger = logging.getLogger(__name__)


# 惩罚阈值统一由 blockchain.config_loader 单一真值源加载（2026-10-01 整改：
# 原与 world_state.py 各重复一份加载逻辑，改一处忘另一处即静默漂移）
_PENALTY_THRESHOLDS = load_penalty_thresholds(logger)


class PenaltyContract:
    """
    分级惩罚合约
    三级惩罚机制（阈值从 config.json 读取）：
    1. 警告级：累计N次背叛(WARNING_THRESHOLD)，扣除积分，链上标记WARNING
    2. 降级级：累计N次背叛(DEMOTION_THRESHOLD)，降低共识投票权重(0.3)
    3. 封禁级：累计N次背叛(BAN_THRESHOLD)或严重恶意行为，链上封禁，拒绝后续交易
    """

    BETRAYAL_SCORE_PENALTY = 20.0   # 每次背叛扣分
    WARNING_THRESHOLD = _PENALTY_THRESHOLDS["warning"]
    DEMOTION_THRESHOLD = _PENALTY_THRESHOLDS["demotion"]
    BAN_THRESHOLD = _PENALTY_THRESHOLDS["ban"]

    def __init__(self, world_state: WorldState, identity_contract=None):
        self._ws = world_state
        self._id_contract = identity_contract  # 关联身份合约

    def apply_penalty(self, agent_id: str, severity: str = "mild") -> Dict:
        """
        对智能体施加惩罚
        :param severity: 惩罚严重程度 mild/moderate/severe
        """
        if not self._ws.is_registered(agent_id):
            return {'success': False, 'error': f'{agent_id} 未注册'}

        betrayal_count = self._ws.get_betrayal_count(agent_id)

        # 根据背叛次数确定惩罚级别
        if betrayal_count >= self.BAN_THRESHOLD or severity == 'severe':
            return self._apply_ban(agent_id, betrayal_count)
        elif betrayal_count >= self.DEMOTION_THRESHOLD or severity == 'moderate':
            return self._apply_demotion(agent_id, betrayal_count)
        else:
            return self._apply_warning(agent_id, betrayal_count)

    def _apply_warning(self, agent_id: str, betrayal_count: int) -> Dict:
        """警告级惩罚"""
        self._ws.add_score(agent_id, -self.BETRAYAL_SCORE_PENALTY)
        if self._id_contract:
            self._id_contract.update_status(agent_id, "warning", ContractCaller.PENALTY)
        logger.info(f"[PenaltyContract] {agent_id} 警告处理: 扣分{self.BETRAYAL_SCORE_PENALTY}（背叛{betrayal_count}次）")
        return {
            'success': True,
            'level': 'WARNING',
            'agent_id': agent_id,
            'score_penalty': -self.BETRAYAL_SCORE_PENALTY,
            'message': f'已警告，扣除{self.BETRAYAL_SCORE_PENALTY}积分',
        }

    def _apply_demotion(self, agent_id: str, betrayal_count: int) -> Dict:
        """降级级惩罚"""
        self._ws.add_score(agent_id, -self.BETRAYAL_SCORE_PENALTY * 1.5)
        # P2-13 修复：改用 WorldState 公共接口，不再直接访问 _identities
        self._ws.update_consensus_weight(agent_id, 0.3)  # 降低共识权重
        self._ws.set_agent_status(agent_id, AgentStatus.DEMOTED)
        if self._id_contract:
            self._id_contract.update_status(agent_id, "demoted", ContractCaller.PENALTY)
        logger.warning(f"[PenaltyContract] {agent_id} 降级处理: 共识权重降为0.3（背叛{betrayal_count}次）")
        return {
            'success': True,
            'level': 'DEMOTED',
            'agent_id': agent_id,
            'new_consensus_weight': 0.3,
            'message': f'已降级，共识权重降为0.3',
        }

    def _apply_ban(self, agent_id: str, betrayal_count: int) -> Dict:
        """封禁级惩罚"""
        # P2-13 修复：改用 WorldState 公共接口
        self._ws.update_consensus_weight(agent_id, 0.0)
        self._ws.set_agent_status(agent_id, AgentStatus.BANNED)
        if self._id_contract:
            self._id_contract.update_status(agent_id, "banned", ContractCaller.PENALTY)
        logger.error(f"[PenaltyContract] ⛔ {agent_id} 已封禁（背叛{betrayal_count}次）")
        return {
            'success': True,
            'level': 'BANNED',
            'agent_id': agent_id,
            'message': f'已封禁，拒绝后续所有交易',
        }

    def is_banned(self, agent_id: str) -> bool:
        """检查智能体是否被封禁"""
        # P2-13 修复：改用 WorldState 公共接口
        status = self._ws.get_agent_status(agent_id)
        return status is not None and status == AgentStatus.BANNED

    def get_penalty_history(self, agent_id: str) -> Dict:
        """获取智能体惩罚记录"""
        # P2-13 修复：改用 WorldState 公共接口和 get_agent_summary
        summary = self._ws.get_agent_summary(agent_id)
        if not summary:
            return {'agent_id': agent_id, 'betrayal_count': 0, 'betrayal_rounds': [],
                    'current_status': None, 'current_score': 0}
        return {
            'agent_id': agent_id,
            'betrayal_count': summary.get('betrayal_count', 0),
            'betrayal_rounds': [],  # 行为详情需通过行为合约查询
            'current_status': summary.get('status'),
            'current_score': summary.get('score', 0),
        }

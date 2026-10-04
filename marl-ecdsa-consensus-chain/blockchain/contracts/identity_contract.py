"""
身份注册智能合约
管理智能体链上身份：注册、查询、状态更新
"""
import enum
import logging
from typing import Optional, Dict, List
from ..ledger.world_state import WorldState, AgentStatus

logger = logging.getLogger(__name__)


class ContractCaller(enum.Enum):
    """合约调用方枚举，替代字符串鉴权"""
    PENALTY = "penalty_contract"
    ADMIN = "admin"
    SYSTEM = "system"


class IdentityContract:
    """
    身份注册合约
    核心接口：
    - register(agent_id, public_key): 智能体注册
    - getPublicKey(agent_id): 查询公钥
    - getStatus(agent_id): 查询状态
    - updateStatus(agent_id, status): 更新状态（仅惩罚合约可调用）
    """

    def __init__(self, world_state: WorldState):
        self._ws = world_state

    def register(self, agent_id: str, public_key_hex: str) -> Dict:
        """
        智能体注册
        校验公钥格式与唯一性
        """
        # P3-11修复: None agent_id 拒绝注册（此前 None 会被存入 _identities 污染链上身份）
        if agent_id is None:
            return {'success': False, 'error': '智能体ID不能为空'}
        if public_key_hex is None:
            return {'success': False, 'error': f'公钥不能为空: {agent_id}'}
        # 格式校验：非压缩公钥应为130个十六进制字符（04 + 64字节）
        if not self._validate_public_key(public_key_hex):
            return {'success': False, 'error': f'公钥格式不合法: {str(public_key_hex)[:20]}...'}

        if self._ws.is_registered(agent_id):
            return {'success': False, 'error': f'智能体 {agent_id} 已注册'}

        success = self._ws.register_agent(agent_id, public_key_hex)
        if success:
            logger.info(f"[IdentityContract] {agent_id} 注册成功")
            return {'success': True, 'agent_id': agent_id}
        return {'success': False, 'error': '注册失败'}

    def get_public_key(self, agent_id: str) -> Optional[str]:
        """查询指定智能体的公钥，用于验签"""
        return self._ws.get_public_key(agent_id)

    def get_status(self, agent_id: str) -> Optional[str]:
        """查询智能体状态（正常/警告/降级/封禁）"""
        status = self._ws.get_agent_status(agent_id)
        return status.value if status else None

    def update_status(self, agent_id: str, new_status: str, caller: ContractCaller = ContractCaller.PENALTY) -> Dict:
        """
        更新智能体状态（仅授权调用方可调用）
        :param caller: 调用方枚举，必须为 ContractCaller.PENALTY 或 ContractCaller.ADMIN
        """
        if caller not in (ContractCaller.PENALTY, ContractCaller.ADMIN):
            return {'success': False, 'error': f'无权限：调用方 {caller} 不允许调用 updateStatus'}

        if not self._ws.is_registered(agent_id):
            return {'success': False, 'error': f'智能体 {agent_id} 不存在'}

        try:
            self._ws.set_agent_status(agent_id, AgentStatus(new_status))
            logger.info(f"[IdentityContract] {agent_id} 状态更新为 {new_status} (caller={caller.value})")
            return {'success': True}
        except ValueError:
            return {'success': False, 'error': f'无效状态值: {new_status}'}

    def list_agents(self) -> List[Dict]:
        """列出所有注册的智能体"""
        return self._ws.get_all_agents_summary()

    def is_active(self, agent_id: str) -> bool:
        """检查智能体是否处于活跃状态"""
        return self._ws.is_active(agent_id)

    @staticmethod
    def _validate_public_key(hex_str: str) -> bool:
        """验证公钥格式（非压缩格式或压缩格式）"""
        if not hex_str:
            return False
        # 非压缩: 04 + 32字节x + 32字节y = 130字符
        # 压缩: 02/03 + 32字节x = 66字符
        return len(hex_str) in (130, 66) and all(c in '0123456789abcdefABCDEF' for c in hex_str)

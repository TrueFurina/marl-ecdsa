"""
MARL协同层模块（P2-D：Bridge 拆分为 5 子组件）

子组件：
  SigningService        — ECDSA签名 + SecurityGuard校验 + nonce管理
  ActionRecorder        — 行为缓冲 → Transaction → 批量上链
  CooperationDetector   — 合作/背叛检测 + 回合累积统计
  SettlementCoordinator — 贡献度评分 + 激励结算 + 奖励融合
  AdaptiveLambdaController — BC→MARL双向反馈：λ动态调节

Bridge 为编排器，对外 API 不变。
"""
from .bc_integration import BlockchainMARLBridge
from .selfish_agent import SelfishAgentWrapper, create_agents
from .signing_service import SigningService
from .action_recorder import ActionRecorder
from .cooperation_detector import CooperationDetector
from .settlement_coordinator import SettlementCoordinator
from .adaptive_lambda import AdaptiveLambdaController

__all__ = [
    'BlockchainMARLBridge', 'SelfishAgentWrapper', 'create_agents',
    'SigningService', 'ActionRecorder', 'CooperationDetector', 'SettlementCoordinator',
    'AdaptiveLambdaController',
]

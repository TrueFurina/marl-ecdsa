"""
世界状态模型
链上维护的全局状态：身份状态、积分状态、行为记录、系统状态
"""
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum

from ..config_loader import load_penalty_thresholds

logger = logging.getLogger(__name__)

# 惩罚阈值统一由 blockchain.config_loader 单一真值源加载（2026-10-01 整改：
# 原与 penalty_contract.py 各重复一份加载逻辑，改一处忘另一处即静默漂移）
_PENALTY_THRESHOLDS = load_penalty_thresholds(logger)


class AgentStatus(str, Enum):
    # 注：各状态对应的背叛次数阈值由 config.json 的 blockchain.penalty_thresholds
    # 驱动（见上方 _PENALTY_THRESHOLDS），下方注释中的数字为该配置的默认值，
    # 修改阈值请改 config.json，勿改此处注释数字以外的任何内容。
    ACTIVE = "active"       # 正常
    WARNING = "warning"     # 警告（累计背叛次数达 penalty_thresholds["warning"]，默认 10）
    DEMOTED = "demoted"     # 降级（累计背叛次数达 penalty_thresholds["demotion"]，默认 30；共识权重降至 0.3）
    BANNED = "banned"       # 封禁（累计背叛次数达 penalty_thresholds["ban"]，默认 50；共识权重归零）


@dataclass
class AgentIdentity:
    """智能体链上身份状态"""
    agent_id: str
    public_key_hex: str         # 链上存储的公钥（十六进制）
    status: AgentStatus = AgentStatus.ACTIVE
    registered_at: int = field(default_factory=lambda: int(time.time() * 1000))
    consensus_weight: float = 1.0   # 共识投票权重（降级后降低）


@dataclass
class AgentScore:
    """智能体积分与贡献状态"""
    agent_id: str
    score: float = 0.0              # 当前激励积分
    cumulative_contribution: float = 0.0  # 累计贡献值
    betrayal_count: int = 0         # 背叛次数
    cooperation_rounds: int = 0     # 成功合作轮次


@dataclass
class AgentBehavior:
    """智能体行为记录"""
    agent_id: str
    action_hashes: List[str] = field(default_factory=list)   # 历史行为哈希
    betrayal_rounds: List[int] = field(default_factory=list)  # 背叛的区块高度
    last_active_block: int = 0


class WorldState:
    """
    世界状态管理器
    存储并管理所有链上智能体状态
    状态随每个区块的确认而更新
    """

    def __init__(self):
        # 身份注册表: {agent_id: AgentIdentity}
        self._identities: Dict[str, AgentIdentity] = {}
        # 积分状态: {agent_id: AgentScore}
        self._scores: Dict[str, AgentScore] = {}
        # 行为记录: {agent_id: AgentBehavior}
        self._behaviors: Dict[str, AgentBehavior] = {}
        # 系统状态
        self._current_height: int = 0
        self._total_transactions: int = 0
        self._online_agents: int = 0

    # -------------------------------------------------------------------------
    # 身份管理
    # -------------------------------------------------------------------------

    def register_agent(self, agent_id: str, public_key_hex: str) -> bool:
        """
        注册智能体身份（对应身份合约的 register 方法）
        :return: True=注册成功，False=已存在
        """
        if agent_id in self._identities:
            logger.warning(f"[WorldState] {agent_id} 已注册，拒绝重复注册")
            return False

        self._identities[agent_id] = AgentIdentity(
            agent_id=agent_id,
            public_key_hex=public_key_hex,
        )
        self._scores[agent_id] = AgentScore(agent_id=agent_id)
        self._behaviors[agent_id] = AgentBehavior(agent_id=agent_id)
        logger.info(f"[WorldState] 智能体 {agent_id} 注册成功")
        return True

    def get_public_key(self, agent_id: str) -> Optional[str]:
        """查询智能体公钥（对应 getPublicKey 合约方法）"""
        identity = self._identities.get(agent_id)
        return identity.public_key_hex if identity else None

    def get_agent_status(self, agent_id: str) -> Optional[AgentStatus]:
        """查询智能体状态"""
        identity = self._identities.get(agent_id)
        return identity.status if identity else None

    def is_registered(self, agent_id: str) -> bool:
        return agent_id in self._identities

    def is_active(self, agent_id: str) -> bool:
        identity = self._identities.get(agent_id)
        return identity is not None and identity.status != AgentStatus.BANNED

    # -------------------------------------------------------------------------
    # 积分与贡献
    # -------------------------------------------------------------------------

    def add_score(self, agent_id: str, delta: float):
        """为智能体添加/扣除积分"""
        if agent_id not in self._scores:
            logger.warning(f"[WorldState] {agent_id} 未注册，无法更新积分")
            return
        self._scores[agent_id].score += delta
        if delta > 0:
            self._scores[agent_id].cumulative_contribution += delta
        logger.debug(f"[WorldState] {agent_id} 积分变化 {delta:+.2f}，当前 {self._scores[agent_id].score:.2f}")

    def get_score(self, agent_id: str) -> float:
        """
        获取智能体积分
        P2-13 修复：对未注册 agent 抛出 KeyError 而非返回默认值，
        防止注册遗漏的 bug 被掩盖
        """
        if agent_id not in self._scores:
            raise KeyError(f"[WorldState] agent '{agent_id}' 未注册，无法获取积分")
        return self._scores[agent_id].score

    def get_all_scores(self) -> Dict[str, float]:
        return {aid: s.score for aid, s in self._scores.items()}

    def get_contribution(self, agent_id: str) -> float:
        """获取智能体累计贡献值。未注册agent直接返回0.0（不创建假AgentScore对象）"""
        score = self._scores.get(agent_id)
        if score is None:
            return 0.0
        return score.cumulative_contribution

    # -------------------------------------------------------------------------
    # 行为记录与惩罚
    # -------------------------------------------------------------------------

    def record_action(self, agent_id: str, action_hash: str, block_height: int):
        """记录智能体行为哈希"""
        if agent_id in self._behaviors:
            self._behaviors[agent_id].action_hashes.append(action_hash)
            self._behaviors[agent_id].last_active_block = block_height

    def record_betrayal(self, agent_id: str, block_height: int):
        """记录背叛行为并触发分级惩罚"""
        if agent_id not in self._scores:
            return

        self._scores[agent_id].betrayal_count += 1
        count = self._scores[agent_id].betrayal_count

        if agent_id in self._behaviors:
            self._behaviors[agent_id].betrayal_rounds.append(block_height)

        # 分级惩罚（阈值从 config.json 读取，集中管理）
        identity = self._identities.get(agent_id)
        if identity:
            if count >= _PENALTY_THRESHOLDS["ban"]:
                # 封禁级
                identity.status = AgentStatus.BANNED
                identity.consensus_weight = 0.0
                logger.warning(f"[WorldState] ⛔ {agent_id} 已封禁（背叛{count}次）")
            elif count >= _PENALTY_THRESHOLDS["demotion"]:
                # 降级级
                identity.status = AgentStatus.DEMOTED
                identity.consensus_weight = 0.3
                logger.warning(f"[WorldState] ⚠️ {agent_id} 已降级（背叛{count}次）")
            elif count >= _PENALTY_THRESHOLDS["warning"]:
                # 警告级
                identity.status = AgentStatus.WARNING
                logger.info(f"[WorldState] ℹ️ {agent_id} 已警告（背叛{count}次）")

    def record_cooperation(self, agent_id: str):
        """记录合作成功"""
        if agent_id in self._scores:
            self._scores[agent_id].cooperation_rounds += 1

    def get_betrayal_count(self, agent_id: str) -> int:
        return self._scores.get(agent_id, AgentScore(agent_id)).betrayal_count

    def get_consensus_weight(self, agent_id: str) -> float:
        """获取智能体共识投票权重（贡献度正相关）"""
        identity = self._identities.get(agent_id)
        if not identity:
            return 0.0
        return identity.consensus_weight

    # ── P2-13: 公共接口封装 ──
    # 避免合约直接访问 _identities/_scores/_behaviors 私有属性

    def update_consensus_weight(self, agent_id: str, weight: float):
        """更新智能体共识投票权重（公共接口，替代直接修改 _identities）"""
        if agent_id not in self._identities:
            logger.warning(f"[WorldState] {agent_id} 未注册，无法更新权重")
            return
        self._identities[agent_id].consensus_weight = weight
        logger.debug(f"[WorldState] {agent_id} 权重更新为 {weight}")

    def set_agent_status(self, agent_id: str, status: AgentStatus):
        """设置智能体状态（公共接口，替代直接修改 _identities）"""
        if agent_id not in self._identities:
            logger.warning(f"[WorldState] {agent_id} 未注册，无法设置状态")
            return
        self._identities[agent_id].status = status
        logger.info(f"[WorldState] {agent_id} 状态更新为 {status}")

    def get_all_agent_ids(self) -> List[str]:
        """获取所有已注册的智能体 ID（公共接口，替代 _identities.keys()）"""
        return list(self._identities.keys())

    # -------------------------------------------------------------------------
    # 系统状态
    # -------------------------------------------------------------------------

    def update_system_state(self, height: int, tx_count: int, online_count: int):
        self._current_height = height
        self._total_transactions += tx_count
        self._online_agents = online_count

    def get_system_state(self) -> Dict:
        return {
            'block_height': self._current_height,
            'total_transactions': self._total_transactions,
            'online_agents': self._online_agents,
            'registered_agents': len(self._identities),
        }

    def get_agent_summary(self, agent_id: str) -> Dict:
        """获取智能体完整摘要"""
        identity = self._identities.get(agent_id)
        score = self._scores.get(agent_id)
        behavior = self._behaviors.get(agent_id)

        if not identity:
            return {}

        return {
            'agent_id': agent_id,
            'status': identity.status,
            'consensus_weight': identity.consensus_weight,
            'score': score.score if score else 0,
            'cumulative_contribution': score.cumulative_contribution if score else 0,
            'betrayal_count': score.betrayal_count if score else 0,
            'cooperation_rounds': score.cooperation_rounds if score else 0,
            'last_active_block': behavior.last_active_block if behavior else 0,
        }

    def get_all_agents_summary(self) -> List[Dict]:
        return [self.get_agent_summary(aid) for aid in self._identities.keys()]

"""
激励结算智能合约
核心功能：
1. 多维度贡献度量化：任务完成度(40%) + 协作贡献度(35%) + 行为合规性(25%)
2. 自动化激励结算：基础奖励 + 贡献加成 + 背叛惩罚
3. 数学上保证「诚实合作期望收益 > 背叛期望收益」

链接MARL双向协同：
total_reward = env_reward + λ * bc_score
"""
import logging
from typing import Dict, List, Optional, Tuple

from ..ledger.world_state import WorldState, AgentStatus

logger = logging.getLogger(__name__)


class ContributionScore:
    """单轮贡献度评分"""
    def __init__(
        self,
        agent_id: str,
        task_score: float,       # 任务完成度 [0,1]
        cooperation_score: float, # 协作贡献度 [0,1]
        compliance_score: float,  # 行为合规性 [0,1]
    ):
        self.agent_id = agent_id
        self.task_score = task_score
        self.cooperation_score = cooperation_score
        self.compliance_score = compliance_score

    @property
    def weighted_score(self) -> float:
        """加权综合贡献度（Shapley值风格推导）

        权重推导：
        - κ_task=0.40: 任务贡献边际值高（Shapley: 高方差维度→高权重）
        - κ_coop=0.35: 协作正外部性补偿（合作收益溢出到其他智能体）
        - κ_compliance=0.25: 合规基础份额（对称性剩余分配）

        约束：κ_task + κ_coop + κ_compliance = 1
        实验校准：σ(task_variance)≈0.1, φ(coop_externality)≈0.05
        """
        return (
            0.40 * self.task_score +
            0.35 * self.cooperation_score +
            0.25 * self.compliance_score
        )


class IncentiveContract:
    """
    激励结算智能合约
    每个区块确认后自动执行结算
    核心规则（数学上保证合作>背叛）：
    - 基础奖励：所有诚实智能体获得基础积分（BASE_REWARD）
    - 行为相关增益：delta = BASE_REWARD + CONTRIB_GAIN * weighted_score
      （weighted_score 由任务/协作/合规三维加权得到，BC 奖励对个体行为可区分，
       贡献越高 delta 越大，消除旧版"常数加成"导致的因果归因缺陷，见 2026-09-01 P0-B 修复）
    - 背叛惩罚：背叛者扣除双倍基础奖励（积分可为负）
    - 保证：E[合作收益] > E[背叛收益]
    """

    BASE_REWARD = 10.0        # 基础奖励积分
    BETRAYAL_PENALTY_MULT = 2.0  # 背叛惩罚倍数（双倍惩罚，与config.json一致）
    TOP_TIER_RATIO = 0.30     # 贡献度前30%享受加成（保留，兼容旧引用）
    TOP_TIER_BONUS = 5.0      # 顶层贡献加成积分（保留，兼容旧引用）
    CONTRIB_GAIN = 10.0       # 贡献增益系数：delta = BASE + CONTRIB_GAIN*weighted_score（行为相关，消除常数加成）

    def __init__(self, world_state: WorldState):
        self._ws = world_state
        # 激励结算历史：{block_height: [settlement_record]}
        self._settlement_history: Dict[int, List[Dict]] = {}

    # -------------------------------------------------------------------------
    # 贡献度量化
    # -------------------------------------------------------------------------

    def compute_contribution(
        self,
        agent_id: str,
        env_reward: float,
        did_cooperate: bool,
        did_betray: bool,
        extra_metrics: Optional[Dict] = None
    ) -> ContributionScore:
        """
        计算智能体本轮贡献度
        :param env_reward: 环境奖励（归一化到[0,1]）
        :param did_cooperate: 是否执行了合作行为
        :param did_betray: 是否背叛（发布虚假观测/不履行承诺）
        :param extra_metrics: 额外评分指标（扩展）
        """
        # 任务完成度：基于环境奖励归一化
        task_score = max(0.0, min(1.0, env_reward))

        # 协作贡献度：合作=1，中性=0.5，背叛=0
        if did_cooperate:
            cooperation_score = 1.0
        elif did_betray:
            cooperation_score = 0.0
        else:
            cooperation_score = 0.5

        # 行为合规性：背叛=0，否则=1
        compliance_score = 0.0 if did_betray else 1.0

        return ContributionScore(
            agent_id=agent_id,
            task_score=task_score,
            cooperation_score=cooperation_score,
            compliance_score=compliance_score,
        )

    # -------------------------------------------------------------------------
    # 自动化激励结算
    # -------------------------------------------------------------------------

    def settle_rewards(
        self,
        block_height: int,
        contribution_scores: List[ContributionScore]
    ) -> Dict[str, float]:
        """
        区块确认后自动执行激励结算

        P0-B 修复（2026-09-01）：将"常数加成"改为"行为相关连续增益"。
        旧逻辑：3 智能体时 top_n=1，delta 恒为 {15,10,10}，与个体行为无关，
        导致 BC 奖励对合作/不合作的普通智能体一视同仁，因果归因不成立。
        新逻辑：delta_i = BASE_REWARD + CONTRIB_GAIN * weighted_score_i
          - 与本智能体自身加权贡献度（任务+协作+合规）连续正相关；
          - 贡献越高 delta 越大，BC 奖励对行为可区分（方差>0 且与行为相关）；
          - 背叛者仍扣双倍基础奖励。
        排序仅用于审计/排行榜，不再决定加成档位。

        :param block_height: 当前区块高度
        :param contribution_scores: 本轮所有智能体的贡献度评分
        :return: 每个智能体的本轮奖励变化 {agent_id: delta}
        """
        if not contribution_scores:
            return {}

        deltas: Dict[str, float] = {}
        records: List[Dict] = []

        # 按综合贡献度排序（用于审计/排行榜，但奖励不再仅由排名决定）
        sorted_agents = sorted(
            contribution_scores,
            key=lambda x: x.weighted_score,
            reverse=True
        )

        n_agents = len(sorted_agents)

        for rank, cs in enumerate(sorted_agents):
            agent_id = cs.agent_id
            delta = 0.0
            reason = []

            if cs.compliance_score == 0.0:
                # 背叛惩罚（扣除双倍基础奖励）
                penalty = -self.BASE_REWARD * self.BETRAYAL_PENALTY_MULT
                delta += penalty
                reason.append(f"背叛惩罚 {penalty:.1f}")
                self._ws.record_betrayal(agent_id, block_height)
            else:
                # 行为相关激励：基础奖励 + 与自身加权贡献度连续的增益
                # 消除"常数加成"：贡献越高，增益越大，BC 奖励对行为可区分
                contrib_gain = self.CONTRIB_GAIN * cs.weighted_score
                delta = self.BASE_REWARD + contrib_gain
                reason.append(
                    f"基础{self.BASE_REWARD:.0f}+贡献增益{contrib_gain:.2f}"
                    f"(加权贡献{cs.weighted_score:.3f})"
                )
                self._ws.record_cooperation(agent_id)

            # 更新世界状态积分
            self._ws.add_score(agent_id, delta)
            # 更新行为记录
            self._ws.record_action(
                agent_id,
                f"ws_{cs.weighted_score:.4f}",
                block_height
            )

            deltas[agent_id] = delta
            records.append({
                'agent_id': agent_id,
                'rank': rank + 1,
                'weighted_score': cs.weighted_score,
                'delta': delta,
                'reason': ', '.join(reason),
                'new_total': self._ws.get_score(agent_id),
            })

        self._settlement_history[block_height] = records
        _min = min(deltas.values())
        _max = max(deltas.values())
        logger.info(
            f"[IncentiveContract] 区块#{block_height} 激励结算完成，"
            f"涉及{n_agents}个智能体，delta范围=[{_min:.2f},{_max:.2f}]"
        )
        return deltas

    # -------------------------------------------------------------------------
    # 链上激励融合接口（MARL核心）
    # -------------------------------------------------------------------------

    def compute_bc_reward(self, agent_id: str, lambda_weight: float = 0.1, use_delta: bool = False) -> float:
        """
        计算区块链奖励项（用于MARL奖励函数融合）

        注意：实际训练流程中使用回合增量（delta）而非累计值，
        由 SettlementCoordinator.update_rewards_and_scores() 管理 _bc_rewards 字典。
        此方法使用累计积分(self._ws.get_score)，为历史兼容接口。

        当 use_delta=True 时，尝试使用最近回合的增量值（需 SettlementCoordinator 提供）。

        total_reward = env_reward + λ * bc_score
        :param lambda_weight: 区块链奖励权重λ
        :param use_delta: 是否使用回合增量而非累计值
        :return: λ * bc_score
        """
        if use_delta and hasattr(self, '_last_deltas') and agent_id in self._last_deltas:
            bc_score = self._last_deltas[agent_id]
        else:
            bc_score = self._ws.get_score(agent_id)
        return lambda_weight * bc_score

    def get_all_bc_rewards(self, lambda_weight: float = 0.1) -> Dict[str, float]:
        """获取所有智能体的区块链奖励项"""
        # P2-13 修复：改用 WorldState 公共接口 get_all_agent_ids()
        return {
            aid: lambda_weight * self._ws.get_score(aid)
            for aid in self._ws.get_all_agent_ids()
        }

    # -------------------------------------------------------------------------
    # 查询接口
    # -------------------------------------------------------------------------

    def get_settlement_history(self, block_height: int) -> List[Dict]:
        return self._settlement_history.get(block_height, [])

    def get_leaderboard(self) -> List[Tuple[str, float]]:
        """获取积分排行榜"""
        scores = self._ws.get_all_scores()
        return sorted(scores.items(), key=lambda x: x[1], reverse=True)

    def get_stats(self) -> Dict:
        """获取激励合约统计信息"""
        scores = self._ws.get_all_scores()
        return {
            'total_agents': len(scores),
            'avg_score': sum(scores.values()) / len(scores) if scores else 0,
            'max_score': max(scores.values()) if scores else 0,
            'min_score': min(scores.values()) if scores else 0,
            'settled_blocks': len(self._settlement_history),
        }

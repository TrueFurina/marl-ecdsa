"""
结算协调服务 — 从 BlockchainMARLBridge 拆分出的子组件（P2-D）
职责：贡献度评分 + 激励结算 + 积分同步 + 奖励融合
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from blockchain.contracts.incentive_contract import ContributionScore

logger = logging.getLogger(__name__)

# P1-5：环境奖励归一化区间，从 config.json 加载（集中管理，不再硬编码在行内）
# _ENV_REWARD_MIN/_ENV_REWARD_MAX 定义归一化输入的原始区间 [min, max] → 映射到 [0.0, 1.0]。
# 兜底默认值 -1.5 / 2.0 与修复前硬编码的映射完全一致
#   (env_r - (-1.5)) / (2.0 - (-1.5)) == (env_r + 1.5) / 3.5
# 因此默认值下行为零变化；调整只需改 config.json，无需改代码。
_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config.json"
_ENV_REWARD_MIN: float = -1.5
_ENV_REWARD_MAX: float = 2.0

try:
    with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
        _norm_cfg = json.load(f).get("blockchain", {}).get("env_reward_normalization", {})
        _cfg_min = float(_norm_cfg.get("min", _ENV_REWARD_MIN))
        _cfg_max = float(_norm_cfg.get("max", _ENV_REWARD_MAX))
        if _cfg_max > _cfg_min:
            _ENV_REWARD_MIN = _cfg_min
            _ENV_REWARD_MAX = _cfg_max
        else:
            logger.warning(
                f"[SettlementCoordinator] config.json 归一化区间非法 "
                f"(min={_cfg_min} >= max={_cfg_max})，使用默认值 "
                f"[{_ENV_REWARD_MIN}, {_ENV_REWARD_MAX}]"
            )
except Exception as e:
    logger.warning(
        f"[SettlementCoordinator] 加载 config.json 失败: {e}, "
        f"使用默认归一化区间 [{_ENV_REWARD_MIN}, {_ENV_REWARD_MAX}]"
    )

# 与 P1-5 同型：bc_reward 裁剪区间，从 config.json 加载（集中管理，不再硬编码在行内）
# _BC_REWARD_CLIP_MIN/_BC_REWARD_CLIP_MAX 定义 compute_total_reward 中 bc_reward 的
# 裁剪区间，防止链上激励项主导总奖励。
# 兜底默认值 -20.0 / 20.0 与修复前硬编码完全一致，故默认值下表达式恒等于原式。
_BC_REWARD_CLIP_MIN: float = -20.0
_BC_REWARD_CLIP_MAX: float = 20.0

try:
    with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
        _clip_cfg = json.load(f).get("blockchain", {}).get("bc_reward_clip", {})
        _cfg_cmin = float(_clip_cfg.get("min", _BC_REWARD_CLIP_MIN))
        _cfg_cmax = float(_clip_cfg.get("max", _BC_REWARD_CLIP_MAX))
        if _cfg_cmax > _cfg_cmin:
            _BC_REWARD_CLIP_MIN = _cfg_cmin
            _BC_REWARD_CLIP_MAX = _cfg_cmax
        else:
            logger.warning(
                f"[SettlementCoordinator] config.json 裁剪区间非法 "
                f"(min={_cfg_cmin} >= max={_cfg_cmax})，使用默认值 "
                f"[{_BC_REWARD_CLIP_MIN}, {_BC_REWARD_CLIP_MAX}]"
            )
except Exception as e:
    logger.warning(
        f"[SettlementCoordinator] 加载 config.json 裁剪区间失败: {e}, "
        f"使用默认值 [{_BC_REWARD_CLIP_MIN}, {_BC_REWARD_CLIP_MAX}]"
    )


class SettlementCoordinator:
    """
    激励结算与奖励融合服务

    封装完整结算流水线：
    1. compute_contribution_scores() — 构造各智能体贡献度评分
    2. settle() — 调用激励合约结算（或模拟结算）
    3. update_rewards_and_scores() — 更新 bc_rewards/bc_scores
    4. compute_total_reward() — 奖励融合公式 total = env + λ*bc
    5. get_bc_scores() — 累计积分查询（委托 WorldState）
    6. get_bc_rewards() — 本回合积分变化查询

    P2-C 修复：WorldState 为唯一积分源（有 incentive_contract 时）
    _bc_scores 仅在 ablate 模式下作为 fallback
    """

    def __init__(
        self,
        incentive_contract=None,
        n_agents: int = 3,
        lambda_weight: float = 0.1,
        env_reward_min: Optional[float] = None,
        env_reward_max: Optional[float] = None,
    ):
        """
        :param incentive_contract: 激励合约，None 表示 ablate 模拟模式
        :param n_agents: 智能体数量
        :param lambda_weight: 区块链激励融合系数 λ
        :param env_reward_min: 环境奖励归一化下界，None 表示取 config.json 配置值
        :param env_reward_max: 环境奖励归一化上界，None 表示取 config.json 配置值
        """
        self.incentive_contract = incentive_contract
        self.lambda_weight = lambda_weight

        # 环境奖励归一化区间（P1-5：取自 config.json，可被构造参数覆盖）
        self.env_reward_min = (
            _ENV_REWARD_MIN if env_reward_min is None else float(env_reward_min)
        )
        self.env_reward_max = (
            _ENV_REWARD_MAX if env_reward_max is None else float(env_reward_max)
        )
        if self.env_reward_max <= self.env_reward_min:
            logger.warning(
                f"[SettlementCoordinator] 归一化区间非法 "
                f"(min={self.env_reward_min} >= max={self.env_reward_max})，"
                f"回退到配置值 [{_ENV_REWARD_MIN}, {_ENV_REWARD_MAX}]"
            )
            self.env_reward_min = _ENV_REWARD_MIN
            self.env_reward_max = _ENV_REWARD_MAX

        # 链上累计积分（仅 ablate 模式 fallback）
        self._bc_scores: Dict[str, float] = {
            f"agent_{i}": 0.0 for i in range(n_agents)
        }

        # 本回合积分变化量（每回合重置）
        self._bc_rewards: Dict[str, float] = {
            f"agent_{i}": 0.0 for i in range(n_agents)
        }

    def compute_contribution_scores(
        self,
        agent_ids: List[str],
        env_rewards: List[float],
        coop_results: Dict[str, tuple],
    ) -> List[ContributionScore]:
        """
        构造各智能体的贡献度评分

        :param agent_ids: 智能体 ID 列表
        :param env_rewards: 环境奖励列表
        :param coop_results: {agent_id: (did_cooperate, did_betray)}
        :return: List[ContributionScore]
        """
        scores = []
        for i, agent_id in enumerate(agent_ids):
            did_cooperate, did_betray = coop_results.get(
                agent_id, (False, False)
            )
            env_r = float(env_rewards[i]) if i < len(env_rewards) else 0.0
            # 归一化环境奖励到 [0, 1]
            # P2修复：SimpleSpreadEnv的local_reward实际范围约[-1.0, 2.0]
            # 修正映射区间为 [-1.5, 2.0] → [0.0, 1.0]，更贴合实际奖励分布
            # 原公式 (env_r + 5) / 10 假设范围[-5,5]，导致大部分奖励被压缩到0.3-0.4区间
            # P1-5：区间边界改由 config.json 的 blockchain.env_reward_normalization
            # 提供（默认 min=-1.5, max=2.0，与此处历史值等价）
            _norm_span = self.env_reward_max - self.env_reward_min
            norm_env_r = max(0.0, min(1.0, (env_r - self.env_reward_min) / _norm_span))

            if self.incentive_contract is not None:
                cs = self.incentive_contract.compute_contribution(
                    agent_id=agent_id,
                    env_reward=norm_env_r,
                    did_cooperate=did_cooperate,
                    did_betray=did_betray,
                )
            else:
                # 模拟模式（无激励合约）
                cs = ContributionScore(
                    agent_id=agent_id,
                    task_score=norm_env_r,
                    cooperation_score=(
                        1.0 if did_cooperate
                        else (0.0 if did_betray else 0.5)
                    ),
                    compliance_score=0.0 if did_betray else 1.0,
                )
            scores.append(cs)
        return scores

    def settle(
        self,
        episode: int,
        scores: List[ContributionScore],
    ) -> Dict[str, float]:
        """
        激励结算

        :param episode: 回合编号
        :param scores: 贡献度评分列表
        :return: {agent_id: delta} 各智能体本回合积分变化量
        """
        if self.incentive_contract is not None:
            deltas = self.incentive_contract.settle_rewards(episode, scores)
        else:
            deltas = self._simulate_settlement(scores)
        return deltas

    def update_rewards_and_scores(self, deltas: Dict[str, float]) -> None:
        """
        更新本回合 bc_reward 和累计 bc_scores

        P2-C 修复：WorldState 为唯一积分源（有 incentive_contract 时）
        _bc_scores 仅在 ablate 模式（无 incentive_contract）下更新
        """
        for agent_id, delta in deltas.items():
            if self.incentive_contract is None:
                # ablate 模式：无 WorldState，_bc_scores 是唯一源
                self._bc_scores[agent_id] = self._bc_scores.get(agent_id, 0.0) + delta
            # 正常模式：settle_rewards() 已更新 WorldState，无需再更新 _bc_scores
            self._bc_rewards[agent_id] = delta

    def compute_total_reward(self, agent_id: str, env_reward: float) -> float:
        """
        计算融合区块链激励后的总奖励
        total_reward = env_reward + λ * bc_reward
        """
        bc_reward = self._bc_rewards.get(agent_id, 0.0)
        # 归一化：将 bc_reward 裁剪到 [_BC_REWARD_CLIP_MIN, _BC_REWARD_CLIP_MAX] 防止主导奖励
        # （边界由 config.json 的 blockchain.bc_reward_clip 提供，默认 -20.0 / 20.0）
        bc_reward_clipped = max(_BC_REWARD_CLIP_MIN, min(_BC_REWARD_CLIP_MAX, bc_reward))
        total = env_reward + self.lambda_weight * bc_reward_clipped
        return total

    def get_all_total_rewards(
        self,
        env_rewards: List[float],
        agent_ids: List[str],
    ) -> List[float]:
        """批量计算所有智能体的融合奖励"""
        return [
            self.compute_total_reward(aid, env_rewards[i])
            for i, aid in enumerate(agent_ids)
        ]

    def get_bc_scores(self) -> Dict[str, float]:
        """
        获取累计积分（用于展示/排行榜）

        P2-C修复：WorldState 为权威积分源（有 incentive_contract 时委托 WorldState）
        ablate 模式下使用 _bc_scores fallback
        """
        if self.incentive_contract is not None:
            try:
                return dict(self.incentive_contract._ws.get_all_scores())
            except Exception as e:
                logger.warning(
                    f"[SettlementCoordinator] WorldState积分读取失败，"
                    f"fallback到_bc_scores: {e}"
                )
        return dict(self._bc_scores)

    def get_bc_rewards(self) -> Dict[str, float]:
        """获取本回合积分变化（用于奖励计算）"""
        return dict(self._bc_rewards)

    def _simulate_settlement(
        self, scores: List[ContributionScore]
    ) -> Dict[str, float]:
        """模拟模式：直接计算激励 delta（温和惩罚策略，降方差）"""
        deltas = {}
        for cs in scores:
            aid = cs.agent_id
            if cs.compliance_score == 0.0:
                # 背叛：温和惩罚（降至-8，避免方差爆炸）
                delta = -8.0
            else:
                # 合作：基础奖励 + 贡献加成
                delta = 10.0 + 5.0 * cs.weighted_score
            deltas[aid] = delta
        return deltas

    def get_stats(self) -> Dict:
        """获取结算统计"""
        return {
            'bc_scores': dict(self._bc_scores),
            'bc_rewards': dict(self._bc_rewards),
            'lambda_weight': self.lambda_weight,
        }

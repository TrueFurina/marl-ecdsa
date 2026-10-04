"""
CW-PBFT 贡献加权拜占庭容错共识算法
Contribution-Weighted Practical Byzantine Fault Tolerance

核心设计：
1. 节点准入：仅完成身份注册的共识节点可参与
2. 主节点选举：轮询制，每10个区块轮换一次
3. 投票权重：与历史贡献度正相关
4. 共识流程：预准备→准备→提交，达成2/3以上权重同意即确认
5. 拜占庭容错：支持 ⌊(n-1)/3⌋ 个恶意节点

简化实现（单机模拟版）：
- 去掉网络I/O，用本地模拟消息传递
- 保留完整的三阶段共识逻辑
- 支持多节点贡献权重计算
"""
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# P1-4：Shapley 贡献维度权重（κ）单一真源
#
# κ 三元组此前在 3 处各自内联：config.json / incentive_contract.ContributionScore /
# cw_pbft.get_consensus_stats()，改一处忘两处即口径漂移。此处统一从 config.json 的
# blockchain.contribution_weights 读取，兜底默认值 0.40 / 0.35 / 0.25 与修复前内联
# 常量逐值一致 —— **对外口径零变化**（设计报告/答辩材料中的 0.40/0.35/0.25 不变）。
# --------------------------------------------------------------------------- #
_CONFIG_PATH: Path = Path(__file__).resolve().parent.parent.parent / "config.json"
_KAPPA_DEFAULTS: Dict[str, float] = {
    'task_score': 0.40,
    'cooperation_score': 0.35,
    'compliance_score': 0.25,
}
# Shapley 校准输入（σ / φ）：答辩材料已明确 κ 是「公式值再校准」的终值
# （κ_task: 1/3+σ/3≈0.37 → 上调至 0.40；κ_compliance: 1/3−σ/3−φ/3≈0.28 → 下调至 0.25）。
# 因此 κ **不可**按 σ/φ 反算重出 —— 那会把对外口径改成 0.3667/0.2833。σ/φ 仅作声明值回显。
SIGMA: float = 0.1      # 任务维度观测方差（校准输入，非实时统计）
PHI: float = 0.05       # 协作正外部性系数（校准输入，非实时统计）


def _load_contribution_weights() -> Tuple[float, float, float]:
    """从 config.json 读取 κ 三元组，缺失或非法时回退默认值。

    校验 Shapley 归一约束 κ_task + κ_coop + κ_compliance = 1；不满足则整体回退
    默认值并告警（fail-safe：宁可用已知正确的常量，也不用一份不自洽的配置）。

    :return: (κ_task, κ_coop, κ_compliance)
    """
    try:
        if _CONFIG_PATH.exists():
            with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            cw = cfg.get('blockchain', {}).get('contribution_weights', {})
            k_task = float(cw.get('task_score', _KAPPA_DEFAULTS['task_score']))
            k_coop = float(cw.get('cooperation_score', _KAPPA_DEFAULTS['cooperation_score']))
            k_comp = float(cw.get('compliance_score', _KAPPA_DEFAULTS['compliance_score']))
            if abs(k_task + k_coop + k_comp - 1.0) < 1e-6:
                return (k_task, k_coop, k_comp)
            logger.warning(
                f"[CW-PBFT] config.json contribution_weights 之和 "
                f"={k_task + k_coop + k_comp:.6f} ≠ 1，回退默认值 {_KAPPA_DEFAULTS}"
            )
    except Exception as e:
        logger.warning(
            f"[CW-PBFT] 加载 config.json contribution_weights 失败: {e}，"
            f"回退默认值 {_KAPPA_DEFAULTS}"
        )
    return (
        _KAPPA_DEFAULTS['task_score'],
        _KAPPA_DEFAULTS['cooperation_score'],
        _KAPPA_DEFAULTS['compliance_score'],
    )


_KAPPA_TASK, _KAPPA_COOP, _KAPPA_COMPLIANCE = _load_contribution_weights()


class ConsensusState(str, Enum):
    IDLE = "idle"               # 空闲
    PRE_PREPARE = "pre_prepare" # 预准备阶段
    PREPARE = "prepare"         # 准备阶段
    COMMIT = "commit"           # 提交阶段
    COMMITTED = "committed"     # 已确认
    VIEW_CHANGE = "view_change" # 视图切换


@dataclass
class ConsensusVote:
    """共识投票"""
    voter_id: str
    block_hash: str
    phase: str          # pre_prepare / prepare / commit
    weight: float
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))
    signature_hex: str = ""


class CWPBFTConsensus:
    """
    贡献加权PBFT共识引擎

    权重推导（Shapley值风格）：
    基础份额：κ_0 = 1/3（对称性初始分配）
    任务贡献调整：κ_task = 1/3 + σ(task_variance)/3（高方差→更高边际贡献）
    协作正外部性：κ_coop = 1/3 + φ(cooperation_externality)/3（合作产生正外部性→补偿）
    合规基础份额：κ_compliance = 1/3 - σ/3 - φ/3（剩余份额归合规）

    约束：κ_task + κ_coop + κ_compliance = 1

    实验校准：σ≈0.1, φ≈0.05 → κ_task≈0.40, κ_coop≈0.35, κ_compliance≈0.25
    这与Shapley值理论一致：边际贡献大的维度获得更高权重

    P1-8修复：
    - 新注册节点初始权重为INITIAL_WEIGHT=0.3（**未结算**临时权重，用于女巫门控）
    - 权重下界MIN_WEIGHT=0.1，确保非封禁节点权重不会降至0（避免失去投票权）
    - update_weight()对非封禁节点使用 clip(new_weight, MIN_WEIGHT, MAX_WEIGHT) 保护

    P1-3修复（语义澄清，数值一律不变）：
    - INITIAL_WEIGHT=0.3 与已结算区间 [WEIGHT_BASE, MAX_WEIGHT]=[1.0, 1.5] 是**两个
      不同区段**，不是同一条爬升曲线：首次结算即从 0.3 跳到 ≥1.0。旧注释写的"需累积
      贡献后逐步提升"与实现不符，已更正 —— 低初值的实际作用是女巫门控（新身份无法
      立刻左右 2/3 阈值），而非连续爬升。
    - 权重公式常量 WEIGHT_BASE / WEIGHT_GAIN 提到类级，bc_integration 侧不再内联，
      杜绝两侧漂移。

    使用方式：
    1. 初始化：传入共识节点列表
    2. 开始共识：propose_block()
    3. 收集投票：receive_vote()
    4. 检查是否达成共识：check_consensus()
    """

    BLOCKS_PER_ROTATION = 10    # 每10个区块轮换主节点
    CONSENSUS_TIMEOUT_MS = 5000 # 5秒共识超时
    # P1-8修复：权重下界保护常量
    MIN_WEIGHT = 0.1            # 非封禁节点权重最低值，防止权重降至0失去投票权
    MAX_WEIGHT = 1.5            # 权重硬上界（P1-15修复：限制单个节点权重上限，对应 R 判据安全设计）
    EPOCH_ROUNDS = 50           # 纪元长度：纪元内权重冻结，纪元末统一更新延迟生效
    PARTICIPATION_FLOOR = 0.25  # 温和衰减下限系数：单纪元零参与权重最多衰减至25%
    # P1-3修复：已结算贡献权重的单一真源 w = WEIGHT_BASE + WEIGHT_GAIN * weighted_score。
    # weighted_score ∈ [0,1] ⇒ w ∈ [1.0, 1.5]，与 MIN/MAX_WEIGHT 的钳制区间一致。
    WEIGHT_BASE = 1.0           # 已结算权重基线（weighted_score=0 时的取值）
    WEIGHT_GAIN = 0.5           # 贡献增益系数（weighted_score=1 时 w=1.5）
    # 未结算（新注册）节点的临时权重。注意它与已结算区间是两段式跳变关系，
    # 不是同一条曲线上的起点 —— 首次结算即跃迁到 ≥ WEIGHT_BASE。
    # 数值保持 0.3 不变（女巫门控语义依赖"新身份 < 已结算基线"）。
    INITIAL_WEIGHT = 0.3
    # 共识权重法定阈值：达成 2/3 以上投票权重即确认（贡献加权 PBFT 的安全边界）
    WEIGHT_QUORUM_RATIO = 2 / 3

    def __init__(self, node_id: str, consensus_nodes: List[str]):
        """
        :param node_id: 本节点ID
        :param consensus_nodes: 所有共识节点的ID列表
        """
        self.node_id = node_id
        self.consensus_nodes = list(consensus_nodes)
        self.n = len(consensus_nodes)               # 节点总数
        self.f = (self.n - 1) // 3                 # 最大容错数

        # 当前视图号（用于主节点选举）
        self._view = 0
        # 当前共识轮次状态
        self._state = ConsensusState.IDLE
        # 当前提议区块哈希
        self._current_block_hash: Optional[str] = None
        # 投票收集：{phase: {voter_id: vote}}
        self._votes: Dict[str, Dict[str, ConsensusVote]] = {
            'prepare': {},
            'commit': {},
        }
        # 节点贡献权重：{node_id: weight}
        # P1-8修复：新注册节点初始权重为INITIAL_WEIGHT而非1.0
        self._weights: Dict[str, float] = {nid: self.INITIAL_WEIGHT for nid in consensus_nodes}
        # 总权重
        self._total_weight: float = sum(self._weights.values())
        # 共识开始时间
        self._consensus_start_ms: int = 0
        # 权重演化追踪：每轮记录权重变化
        self._weight_history: List[Dict] = []
        # 共识成功/失败计数
        self.consensus_success_count: int = 0
        self.consensus_fail_count: int = 0
        # 参与率驱动权重展宽（路线C机制，2026-09-23合入主引擎）
        # 语义：每轮记录PREPARE阶段实际投票者 → 纪元末按参与率温和衰减+钳制+归一
        self._part_total: Dict[str, int] = {nid: 0 for nid in consensus_nodes}
        self._part_rounds: int = 0
        self._round_index: int = 0
        self._epoch_index: int = 0
        # 纪元演化追踪：[{epoch, weights, R}]，R=w_max/w_min（有效带宽比）
        self._epoch_history: List[Dict] = []

    # -------------------------------------------------------------------------
    # 主节点管理
    # -------------------------------------------------------------------------

    def get_primary(self, block_height: int) -> str:
        """
        获取指定区块高度的主节点（轮询制）
        每 BLOCKS_PER_ROTATION 个区块轮换一次
        """
        primary_index = (block_height // self.BLOCKS_PER_ROTATION) % self.n
        return self.consensus_nodes[primary_index]

    def is_primary(self, block_height: int) -> bool:
        """当前节点是否为本轮主节点"""
        return self.get_primary(block_height) == self.node_id

    # -------------------------------------------------------------------------
    # 三阶段共识流程
    # -------------------------------------------------------------------------

    def start_consensus(self, block_hash: str) -> ConsensusVote:
        """
        主节点发起共识：PRE-PREPARE阶段
        :return: 预准备投票（广播给其他节点）
        """
        self._state = ConsensusState.PRE_PREPARE
        self._current_block_hash = block_hash
        self._consensus_start_ms = int(time.time() * 1000)
        self._votes = {'prepare': {}, 'commit': {}}

        vote = ConsensusVote(
            voter_id=self.node_id,
            block_hash=block_hash,
            phase='pre_prepare',
            weight=self._weights.get(self.node_id, 1.0),
        )
        logger.info(f"[CW-PBFT] 主节点 {self.node_id} 发起共识: {block_hash[:16]}...")
        return vote

    def receive_pre_prepare(self, block_hash: str, primary_id: str) -> ConsensusVote:
        """
        非主节点收到PRE-PREPARE：验证后进入PREPARE阶段
        :return: 本节点的PREPARE投票
        """
        self._state = ConsensusState.PREPARE
        self._current_block_hash = block_hash
        self._consensus_start_ms = int(time.time() * 1000)

        vote = ConsensusVote(
            voter_id=self.node_id,
            block_hash=block_hash,
            phase='prepare',
            weight=self._weights.get(self.node_id, 1.0),
        )
        logger.debug(f"[CW-PBFT] {self.node_id} 进入PREPARE阶段")
        return vote

    def receive_vote(self, vote: ConsensusVote) -> Optional[ConsensusVote]:
        """
        收到其他节点的投票
        :return: 如果达到阈值，返回下一阶段投票；否则返回None
        """
        if vote.block_hash != self._current_block_hash:
            logger.debug(f"[CW-PBFT] 丢弃不匹配的投票: {vote.voter_id}")
            return None

        # 09-28 修复（全检 #2·女巫门控）：非共识成员身份一律拒收。
        # 成员集合在 __init__ 时由 consensus_nodes 固定，update_weight
        # 也不会新增成员（见 :451 `if node_id in self._weights`），故此处拒收
        # 不影响任何合法节点参与共识，只会挡住伪造身份混入 _votes /
        # 参与率统计（此前伪造身份虽因查表权重为 0 而不影响 Quorum，但仍会
        # 污染 prepare_votes 计数与展宽所需的参与率信号）。
        if vote.voter_id not in self._weights:
            logger.warning(
                f"[CW-PBFT] 拒收非成员投票（女巫门控）: voter={vote.voter_id}"
            )
            return None

        # 09-28 修复（全检 #2·权重权威化）：入库前把自报 weight 覆盖为本地权威值。
        # 存副本而非就地改写入参，避免对调用方持有的对象产生隐式副作用。
        # 这样任何下游读取 `vote.weight` 的消费者（含未来的 get_consensus_stats
        # 扩展）都只能看到权威值，自报字段不再有第二个可信通道。
        auth_weight = self._weights.get(vote.voter_id, 0.0)
        stored = vote if vote.weight == auth_weight else replace(vote, weight=auth_weight)
        if stored.weight != vote.weight:
            logger.warning(
                f"[CW-PBFT] 投票权重纠偏: voter={vote.voter_id} "
                f"自报={vote.weight:.4f} → 权威={stored.weight:.4f}"
            )

        phase = vote.phase
        if phase in self._votes:
            self._votes[phase][vote.voter_id] = stored

        # PREPARE阶段：达到2/3权重 → 进入COMMIT
        if phase == 'prepare' and self._state == ConsensusState.PREPARE:
            if self._check_weight_threshold('prepare'):
                self._state = ConsensusState.COMMIT
                commit_vote = ConsensusVote(
                    voter_id=self.node_id,
                    block_hash=self._current_block_hash,
                    phase='commit',
                    weight=self._weights.get(self.node_id, 1.0),
                )
                logger.debug(f"[CW-PBFT] {self.node_id} 进入COMMIT阶段")
                return commit_vote

        # COMMIT阶段：达到2/3权重 → 共识达成
        if phase == 'commit' and self._state == ConsensusState.COMMIT:
            if self._check_weight_threshold('commit'):
                self._state = ConsensusState.COMMITTED
                logger.info(f"[CW-PBFT] ✅ 共识达成！block_hash={self._current_block_hash[:16]}...")

        return None

    def is_consensus_reached(self) -> bool:
        """共识是否已达成"""
        return self._state == ConsensusState.COMMITTED

    def get_state(self) -> ConsensusState:
        return self._state

    def is_timed_out(self) -> bool:
        """检查共识是否超时"""
        if self._consensus_start_ms == 0:
            return False
        elapsed = int(time.time() * 1000) - self._consensus_start_ms
        return elapsed > self.CONSENSUS_TIMEOUT_MS

    def reset(self):
        """重置共识状态（超时后调用）"""
        self._state = ConsensusState.IDLE
        self._current_block_hash = None
        self._votes = {'prepare': {}, 'commit': {}}
        self._consensus_start_ms = 0

    # -------------------------------------------------------------------------
    # 快速模拟共识（单节点/测试场景）
    # -------------------------------------------------------------------------

    def fast_consensus(self, block_hash: str, proposer: str) -> bool:
        """
        快速模拟共识（用于单节点测试或少于4节点的场景）
        假设所有节点都诚实，直接模拟三阶段投票

        注意：此方法跳过了权重阈值检查，仅适用于测试场景。
        生产环境应使用 simulated_consensus()，它执行完整三阶段+权重阈值检查。
        仅用于测试/少节点场景；生产共识路径请使用 simulated_consensus()。
        """
        self._current_block_hash = block_hash
        self._votes = {'prepare': {}, 'commit': {}}

        # 模拟所有节点投票
        for nid in self.consensus_nodes:
            w = self._weights.get(nid, self.INITIAL_WEIGHT)
            self._votes['prepare'][nid] = ConsensusVote(
                voter_id=nid, block_hash=block_hash,
                phase='prepare', weight=w
            )
            self._votes['commit'][nid] = ConsensusVote(
                voter_id=nid, block_hash=block_hash,
                phase='commit', weight=w
            )

        self._state = ConsensusState.COMMITTED
        self.consensus_success_count += 1
        logger.info(f"[CW-PBFT] 快速共识完成: {block_hash[:16]}...")
        return True

    def simulated_consensus(
        self,
        block_hash: str,
        proposer: str,
        byzantine_nodes: Optional[Set[str]] = None,
    ) -> bool:
        """
        单机版完整三阶段共识模拟（P1-关键架构修复 + P0-D 拜占庭注入）

        P0-D 修复（2026-09-01）：新增 byzantine_nodes 参数，
        支持真实拜占庭容错验证。被标记的节点将拒绝投票
        （省略故障 / 拒绝服务模型），从而真实消费 byz_ratio：
        - 当拜占庭节点权重之和 > 1/3 总权重时，投票权重无法达到
          2/3 阈值，共识将真实失败（而非像 fast_consensus 那样恒为成功）；
        - 无拜占庭节点（默认）时退化为原全诚实路径，训练流程不受影响。

        区别于fast_consensus()：
        - 执行完整PREPARE→COMMIT→FINALIZE三阶段流程
        - 每阶段检查权重阈值：prepare/commit阶段均需总投票权重>2/3总权重
        - 阈值不满足时共识失败（而非像fast_consensus那样直接通过）
        """
        if byzantine_nodes is None:
            byzantine_nodes = set()

        # ── PRE-PREPARE阶段：主节点提议 ──
        self._state = ConsensusState.PRE_PREPARE
        self._current_block_hash = block_hash
        self._consensus_start_ms = int(time.time() * 1000)
        self._votes = {'prepare': {}, 'commit': {}}

        # ── PREPARE阶段：非拜占庭节点投票 ──
        self._state = ConsensusState.PREPARE
        for nid in self.consensus_nodes:
            if nid in byzantine_nodes:
                continue  # 拜占庭节点拒绝投票（省略故障模型）
            w = self._weights.get(nid, self.INITIAL_WEIGHT)
            self._votes['prepare'][nid] = ConsensusVote(
                voter_id=nid, block_hash=block_hash,
                phase='prepare', weight=w
            )

        # 参与率记录：PREPARE 阶段实际投票者计入窗口（路线C机制）。
        # 记录与共识成败解耦——失败轮同样入窗，否则"权重不足→永不成功→
        # 永不展宽"死锁（训练级接线的前提）
        self._record_participation()

        # 检查prepare阶段权重阈值
        if not self._check_weight_threshold('prepare'):
            self._state = ConsensusState.IDLE
            self.consensus_fail_count += 1
            logger.warning(
                f"[CW-PBFT] simulated_consensus PREPARE阶段权重阈值不满足: "
                f"block_hash={block_hash[:16]} | byzantine={len(byzantine_nodes)}"
            )
            return False

        # ── COMMIT阶段：非拜占庭节点投票 ──
        self._state = ConsensusState.COMMIT
        for nid in self.consensus_nodes:
            if nid in byzantine_nodes:
                continue
            w = self._weights.get(nid, self.INITIAL_WEIGHT)
            self._votes['commit'][nid] = ConsensusVote(
                voter_id=nid, block_hash=block_hash,
                phase='commit', weight=w
            )

        # 检查commit阶段权重阈值
        if not self._check_weight_threshold('commit'):
            self._state = ConsensusState.IDLE
            self.consensus_fail_count += 1
            logger.warning(
                f"[CW-PBFT] simulated_consensus COMMIT阶段权重阈值不满足: "
                f"block_hash={block_hash[:16]} | byzantine={len(byzantine_nodes)}"
            )
            return False

        # ── FINALIZE阶段：共识达成 ──
        self._state = ConsensusState.COMMITTED
        self.consensus_success_count += 1
        # 诊断日志。此处 sum(v.weight) **不是**全检 #2 所指的那处自报权重信任：
        # _votes 中的票已由 receive_vote 归一化，v.weight 即权威值；真正的票数
        # 与否决判定一律走 _check_weight_threshold（查表），不读这两个和。
        logger.info(
            f"[CW-PBFT] simulated_consensus完成: {block_hash[:16]} "
            f"| prepare_weight={sum(v.weight for v in self._votes['prepare'].values()):.2f} "
            f"| commit_weight={sum(v.weight for v in self._votes['commit'].values()):.2f} "
            f"| total_weight={self._total_weight:.2f}"
        )
        return True

    # -------------------------------------------------------------------------
    # 权重管理
    # -------------------------------------------------------------------------

    def update_weight(self, node_id: str, new_weight: float):
        """
        更新节点贡献权重（由激励模块调用）

        P1-8修复：
        - 非封禁节点权重受MIN_WEIGHT下界保护，确保不会降至0失去投票权
        - 封禁节点（new_weight <= 0）允许权重为0
        - 计算公式：clip(new_weight, MIN_WEIGHT, MAX_WEIGHT)，其中
          new_weight = WEIGHT_BASE + WEIGHT_GAIN * weighted_score
          （P1-3修复：1.0 / 0.5 提到类级常量，不再在调用侧内联，避免两侧漂移）
        P1-15修复：
        - 非封禁节点权重同时受 MAX_WEIGHT=1.5 硬上界钳制，限制单个节点权重上限
        """
        if node_id in self._weights:
            old = self._weights[node_id]
            # P1-8修复：非封禁节点（new_weight > 0）受下界保护；P1-15：加上界钳制
            if new_weight > 0:
                protected_weight = max(self.MIN_WEIGHT, min(self.MAX_WEIGHT, new_weight))
            else:
                # 封禁节点：权重设为0（明确失去投票权）
                protected_weight = 0.0
            self._weights[node_id] = protected_weight
            self._total_weight = sum(self._weights.values())
            # 记录权重演化
            self._weight_history.append({
                'weights': dict(self._weights),
                'total_weight': self._total_weight,
            })
            logger.debug(f"[CW-PBFT] {node_id} 权重: {old:.2f} → {protected_weight:.2f}")

    def _record_participation(self):
        """
        记录本轮参与率（路线C机制，2026-09-23 合入主引擎）：
        把 PREPARE 阶段实际投票者计入滑窗，供纪元末权重展宽使用。
        仅统计真实存在的节点（防女巫身份混入统计）。
        """
        self._part_rounds += 1
        for nid in self._votes.get('prepare', {}):
            if nid in self._part_total:
                self._part_total[nid] += 1

    def end_of_round_epoch_update(self) -> Optional[Dict]:
        """
        纪元末权重展宽（路线C机制，与论文第3章3.5节/第6章实证对应）：
        w ← clip(w·(FLOOR + (1-FLOOR)·participation), MIN_WEIGHT, MAX_WEIGHT) 后均值归一。

        - 参与率信号仅来自链上可核验的 PREPARE 投票记录，不预设谁是坏节点
        - FLOOR=0.25 温和衰减：单纪元零参与最多衰减至25%，保留误判恢复机会
        - MAX_WEIGHT=1.5 硬钳制 + 均值归一（限制单个节点权重上限，满足 R 判据安全设计）
        - 权重更新延迟生效语义由调用方保证：纪元内冻结，本方法仅在纪元末调用

        返回纪元摘要 dict（epoch/R/honest 调用方自行补充），非纪元末返回 None。
        """
        self._round_index += 1
        if self._round_index % self.EPOCH_ROUNDS != 0 or self._part_rounds == 0:
            return None
        new_w = {}
        banned = []
        for nid in self._weights:
            # 09-28 修复：封禁节点（w<=0）不参与展宽——既不被恢复投票权，也不参与均值归一。
            # 此前 bug：raw=0 经 max(MIN_WEIGHT,·) 被抬到 0.1，再走 update_weight(>0)
            # 把封禁节点静默复活（实测封禁 0.0 → 一个纪元后 0.429），使惩罚合约的
            # 封禁在一个纪元后被自动撤销。
            if self._weights[nid] <= 0:
                banned.append(nid)
                continue
            p = self._part_total.get(nid, 0) / self._part_rounds
            raw = self._weights[nid] * (self.PARTICIPATION_FLOOR
                                        + (1 - self.PARTICIPATION_FLOOR) * p)
            new_w[nid] = max(self.MIN_WEIGHT, min(self.MAX_WEIGHT, raw))
        if new_w:
            mean = sum(new_w.values()) / len(new_w)
            for nid, w in new_w.items():
                # 走 update_weight 以复用下界/上界/历史记录逻辑。
                # new_w 已剔除封禁节点，故此处新权重恒 > 0，不再绕过封禁语义。
                self.update_weight(nid, w / mean)
        if banned:
            logger.info(
                f"[CW-PBFT] 纪元末展宽跳过 {len(banned)} 个封禁节点(w=0): {banned}"
            )
        vals = list(self._weights.values())
        summary = {
            'epoch': self._epoch_index,
            'R': max(vals) / min(vals) if min(vals) > 0 else float('inf'),
            'weights': dict(self._weights),
            'excluded_banned': list(banned),
        }
        self._epoch_history.append(summary)
        self._epoch_index += 1
        # 参与窗口滚动重置（近期行为主导，被误降节点有机会恢复）
        self._part_total = {nid: 0 for nid in self._part_total}
        self._part_rounds = 0
        logger.info(
            f"[CW-PBFT] 纪元{summary['epoch']}权重展宽: R={summary['R']:.2f} "
            f"| w_max={max(vals):.2f} w_min={min(vals):.2f}"
        )
        return summary

    def get_weights(self) -> Dict[str, float]:
        return dict(self._weights)

    def get_weight_history(self) -> List[Dict]:
        """获取权重演化历史记录"""
        return list(self._weight_history)

    # -------------------------------------------------------------------------
    # 内部工具
    # -------------------------------------------------------------------------

    def _check_weight_threshold(self, phase: str) -> bool:
        """
        检查是否达到2/3权重阈值
        CW-PBFT：贡献度越高的节点投票权重越大

        09-28 修复（全检 #2）：累加的权重一律取自**本地权威权重表** ``_weights``，
        不再使用投票结构体里由发送方自填的 ``vote.weight``。

        为什么必须改：网络层 ``network_consensus._verify_vote_signature`` 已对整条
        报文做 ECDSA 验签且 fail-closed（见 :234/:292），但验签只证明
        "发送方确实声称了这个权重"，**并不保证**该权重等于权威表中的值。因此任意
        成员只要签一份 ``weight=1e6`` 的投票，即可**单票越过 2/3 阈值**
        （实测：n=3 时 _total_weight=0.9、阈值仅 0.60，而自报 weight=1.0 的
        **一票即已达标**）。改为查表后，伪造 weight 字段不再产生任何效果。
        """
        if not self._votes.get(phase):
            return False

        voted_weight = 0.0
        for voter_id in self._votes[phase]:
            w = self._weights.get(voter_id, 0.0)
            if w <= 0:
                # 封禁节点（w=0）不计票（09-28 修复 #3 的配套：展宽已不再复活封禁，
                # 此处补全"封禁期间投票亦不计入 Quorum"，避免惩罚被投票路径绕过）
                continue
            voted_weight += w
        threshold = self.WEIGHT_QUORUM_RATIO * self._total_weight

        logger.debug(
            f"[CW-PBFT] {phase}阶段 投票权重={voted_weight:.2f} "
            f"/ 总权重={self._total_weight:.2f} "
            f"/ 阈值={threshold:.2f}"
        )
        return voted_weight >= threshold

    def get_consensus_stats(self) -> Dict:
        """获取共识状态统计"""
        total_rounds = self.consensus_success_count + self.consensus_fail_count
        consensus_success_rate = (
            self.consensus_success_count / total_rounds
            if total_rounds > 0 else 0.0
        )
        return {
            'node_id': self.node_id,
            'state': self._state,
            'n_nodes': self.n,
            'f_tolerance': self.f,
            'prepare_votes': len(self._votes.get('prepare', {})),
            'commit_votes': len(self._votes.get('commit', {})),
            'current_block_hash': self._current_block_hash,
            'weights': self._weights,
            'consensus_success_rate': consensus_success_rate,
            'weight_history': self._weight_history[-10:],
            # P1-4修复：κ 三元组不再内联硬编码，改从 config.json 的
            # blockchain.contribution_weights 读取（与 incentive_contract 同源），
            # 缺失/不自洽时回退 0.40/0.35/0.25。返回键名与取值均保持不变。
            # σ/φ 为声明的校准输入（模块级 SIGMA / PHI），非实时统计量。
            'weight_derivation': {
                'κ_task': _KAPPA_TASK,
                'κ_coop': _KAPPA_COOP,
                'κ_compliance': _KAPPA_COMPLIANCE,
                'sigma': SIGMA,
                'phi': PHI,
            },
        }

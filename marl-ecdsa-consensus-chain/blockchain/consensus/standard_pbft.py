"""
标准PBFT共识算法（等权重基线）
Standard Practical Byzantine Fault Tolerance

与CW-PBFT的唯一区别：所有节点投票权重相等（1/n），不使用贡献度加权。
用于对比实验，证明CW-PBFT贡献加权机制的优越性。

对比维度：
1. 共识延迟：CW-PBFT高贡献节点权重更大 → 少数节点即可达成共识 → 延迟更低
2. 拜占庭容错：CW-PBFT可以降低恶意节点的权重 → 容错能力更强
3. 公平性：CW-PBFT根据实际贡献分配权重 → 激励更公平
4. 抗合谋：CW-PBFT降低低贡献节点权重 → 合谋成本更高
"""
import logging
import time
from dataclasses import replace
from typing import Dict, List, Optional, Set

from .cw_pbft import ConsensusState, ConsensusVote

logger = logging.getLogger(__name__)


class StandardPBFTConsensus:
    """
    标准PBFT共识引擎（等权重基线）

    所有节点权重 = 1.0（相等），阈值 = ceil(2n/3) + 1（节点数计数）
    其余逻辑与CW-PBFT完全一致，仅替换权重计算方式
    """

    BLOCKS_PER_ROTATION = 10
    CONSENSUS_TIMEOUT_MS = 5000

    def __init__(self, node_id: str, consensus_nodes: List[str]):
        self.node_id = node_id
        self.consensus_nodes = list(consensus_nodes)
        self.n = len(consensus_nodes)
        self.f = (self.n - 1) // 3

        self._view = 0
        self._state = ConsensusState.IDLE
        self._current_block_hash: Optional[str] = None
        self._votes: Dict[str, Dict[str, ConsensusVote]] = {
            'prepare': {},
            'commit': {},
        }
        # 等权重：每个节点权重 = 1.0
        self._weights: Dict[str, float] = {nid: 1.0 for nid in consensus_nodes}
        self._total_weight: float = float(self.n)
        self._consensus_start_ms: int = 0
        self.consensus_success_count: int = 0
        self.consensus_fail_count: int = 0

    def get_primary(self, block_height: int) -> str:
        primary_index = (block_height // self.BLOCKS_PER_ROTATION) % self.n
        return self.consensus_nodes[primary_index]

    def is_primary(self, block_height: int) -> bool:
        return self.get_primary(block_height) == self.node_id

    def start_consensus(self, block_hash: str) -> ConsensusVote:
        self._state = ConsensusState.PRE_PREPARE
        self._current_block_hash = block_hash
        self._consensus_start_ms = int(time.time() * 1000)
        self._votes = {'prepare': {}, 'commit': {}}

        vote = ConsensusVote(
            voter_id=self.node_id,
            block_hash=block_hash,
            phase='pre_prepare',
            weight=1.0,
        )
        logger.info(f"[PBFT] 主节点 {self.node_id} 发起共识: {block_hash[:16]}...")
        return vote

    def receive_pre_prepare(self, block_hash: str, primary_id: str) -> ConsensusVote:
        self._state = ConsensusState.PREPARE
        self._current_block_hash = block_hash
        self._consensus_start_ms = int(time.time() * 1000)

        vote = ConsensusVote(
            voter_id=self.node_id,
            block_hash=block_hash,
            phase='prepare',
            weight=1.0,
        )
        return vote

    def receive_vote(self, vote: ConsensusVote) -> Optional[ConsensusVote]:
        if vote.block_hash != self._current_block_hash:
            return None

        # 11-03 修复：把 CW-PBFT 早已具备的「女巫门控」同步到等权基线。
        #
        # CW-PBFT 在 09-28（全检 #2）就加了「非共识成员身份一律拒收」，但等权
        # 基线漏了同一个门控。而 `_check_vote_threshold` 是按
        # `len(self._votes[phase])`（投票者个数）计数的 —— 只要塞进任意伪造的
        # voter_id，就能凭空凑够 ceil(2n/3)。
        #
        # 已实测：n=4（阈值 3）时，单个节点在**零个真实对等节点**参与的情况下，
        # 用 ghost_1/ghost_2/ghost_3 三个捏造身份即可跑完 PREPARE→COMMIT 并宣布
        # 共识达成；同一组伪造投票在 CW-PBFT 下被全部拒收。等权基线是对比实验
        # 的对照组（factory 用 `mode='standard_pbft'` 创建），它的共识安全属性
        # 不应弱于被对照的对象。
        if vote.voter_id not in self._weights:
            logger.warning(
                f"[PBFT] 拒收非成员投票（女巫门控）: voter={vote.voter_id}"
            )
            return None

        # 自报 weight 不作为第二个可信通道：等权模式下权威值恒为 1.0。
        # 存副本而非就地改写入参，避免对调用方持有的对象产生隐式副作用。
        stored = vote if vote.weight == 1.0 else replace(vote, weight=1.0)
        if stored.weight != vote.weight:
            logger.warning(
                f"[PBFT] 投票权重纠偏（等权）: voter={vote.voter_id} "
                f"自报={vote.weight:.4f} → 权威=1.0000"
            )

        phase = vote.phase
        if phase in self._votes:
            self._votes[phase][vote.voter_id] = stored

        if phase == 'prepare' and self._state == ConsensusState.PREPARE:
            if self._check_vote_threshold('prepare'):
                self._state = ConsensusState.COMMIT
                commit_vote = ConsensusVote(
                    voter_id=self.node_id,
                    block_hash=self._current_block_hash,
                    phase='commit',
                    weight=1.0,
                )
                return commit_vote

        if phase == 'commit' and self._state == ConsensusState.COMMIT:
            if self._check_vote_threshold('commit'):
                self._state = ConsensusState.COMMITTED
                self.consensus_success_count += 1
                logger.info(f"[PBFT] 共识达成: {self._current_block_hash[:16]}...")

        return None

    def is_consensus_reached(self) -> bool:
        return self._state == ConsensusState.COMMITTED

    def get_state(self) -> ConsensusState:
        return self._state

    def is_timed_out(self) -> bool:
        if self._consensus_start_ms == 0:
            return False
        elapsed = int(time.time() * 1000) - self._consensus_start_ms
        return elapsed > self.CONSENSUS_TIMEOUT_MS

    def reset(self):
        self._state = ConsensusState.IDLE
        self._current_block_hash = None
        self._votes = {'prepare': {}, 'commit': {}}
        self._consensus_start_ms = 0

    def fast_consensus(self, block_hash: str, proposer: str) -> bool:
        self._current_block_hash = block_hash
        self._votes = {'prepare': {}, 'commit': {}}

        for nid in self.consensus_nodes:
            self._votes['prepare'][nid] = ConsensusVote(
                voter_id=nid, block_hash=block_hash,
                phase='prepare', weight=1.0
            )
            self._votes['commit'][nid] = ConsensusVote(
                voter_id=nid, block_hash=block_hash,
                phase='commit', weight=1.0
            )

        self._state = ConsensusState.COMMITTED
        self.consensus_success_count += 1
        return True

    def simulated_consensus(
        self,
        block_hash: str,
        proposer: str,
        byzantine_nodes: Optional[Set[str]] = None,
    ) -> bool:
        """
        单机版完整三阶段共识模拟（P0-D 拜占庭注入，与CW-PBFT接口一致）

        P0-D 修复（2026-09-01）：新增 byzantine_nodes 参数，支持真实拜占庭容错验证。
        被标记节点拒绝投票（省略故障模型）；按节点数计数，阈值 = ceil(2n/3)。
        - 标准PBFT（等权）对拜占庭更敏感：当拜占庭节点数 > f=(n-1)//3 时共识失败；
        - 无拜占庭（默认）时退化为全诚实路径。

        区别于fast_consensus()：fast_consensus 恒成功且不检查阈值。
        """
        if byzantine_nodes is None:
            byzantine_nodes = set()

        # PRE-PREPARE
        self._state = ConsensusState.PRE_PREPARE
        self._current_block_hash = block_hash
        self._consensus_start_ms = int(time.time() * 1000)
        self._votes = {'prepare': {}, 'commit': {}}

        # PREPARE：非拜占庭节点投票
        self._state = ConsensusState.PREPARE
        for nid in self.consensus_nodes:
            if nid in byzantine_nodes:
                continue
            self._votes['prepare'][nid] = ConsensusVote(
                voter_id=nid, block_hash=block_hash,
                phase='prepare', weight=1.0
            )
        if not self._check_vote_threshold('prepare'):
            self._state = ConsensusState.IDLE
            self.consensus_fail_count += 1
            return False

        # COMMIT：非拜占庭节点投票
        self._state = ConsensusState.COMMIT
        for nid in self.consensus_nodes:
            if nid in byzantine_nodes:
                continue
            self._votes['commit'][nid] = ConsensusVote(
                voter_id=nid, block_hash=block_hash,
                phase='commit', weight=1.0
            )
        if not self._check_vote_threshold('commit'):
            self._state = ConsensusState.IDLE
            self.consensus_fail_count += 1
            return False

        self._state = ConsensusState.COMMITTED
        self.consensus_success_count += 1
        return True

    def _check_vote_threshold(self, phase: str) -> bool:
        """
        标准PBFT：按节点数计数，阈值 = ceil(2n/3)
        （与CW-PBFT的按权重计数不同）
        """
        if not self._votes.get(phase):
            return False

        vote_count = len(self._votes[phase])
        threshold = (2 * self.n + 2) // 3  # ceil(2n/3)

        logger.debug(
            f"[PBFT] {phase}阶段 投票数={vote_count} "
            f"/ 总节点={self.n} / 阈值={threshold}"
        )
        return vote_count >= threshold

    # ----------------------------------------------------------------------
    # 与 CW-PBFT 保持接口一致（供 network_consensus 统一调用）
    # ----------------------------------------------------------------------

    def _check_weight_threshold(self, phase: str) -> bool:
        """别名：等权模式下权重阈值等价于节点数阈值"""
        return self._check_vote_threshold(phase)

    def update_weight(self, node_id: str, new_weight: float):
        """等权模式忽略权重更新（权重恒为1.0），仅记录日志"""
        logger.debug(f"[PBFT] 等权模式忽略权重更新: {node_id} -> {new_weight}")

    def get_weights(self) -> Dict[str, float]:
        """返回等权权重表"""
        return dict(self._weights)

    def get_consensus_stats(self) -> Dict:
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
            'consensus_type': 'standard_pbft',
        }

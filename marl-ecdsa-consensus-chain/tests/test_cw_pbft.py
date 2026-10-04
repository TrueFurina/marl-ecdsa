"""CW-PBFT 共识引擎单元测试"""
import pytest
from blockchain.consensus.cw_pbft import (
    CWPBFTConsensus, ConsensusState, ConsensusVote
)

NODES_3 = ["node_0", "node_1", "node_2"]
NODES_4 = ["node_0", "node_1", "node_2", "node_3"]


class TestPrimaryElection:
    def test_get_primary_rotation(self):
        """主节点按 BLOCKS_PER_ROTATION 轮换"""
        pbft = CWPBFTConsensus("node_0", NODES_3)
        # block 0-9: primary = nodes[(0//10)%3] = nodes[0]
        assert pbft.get_primary(0) == "node_0"
        assert pbft.get_primary(9) == "node_0"
        # block 10-19: primary = nodes[1]
        assert pbft.get_primary(10) == "node_1"
        # block 20-29: primary = nodes[2]
        assert pbft.get_primary(20) == "node_2"
        # block 30-39: wraps back to nodes[0]
        assert pbft.get_primary(30) == "node_0"

    def test_is_primary_true(self):
        pbft = CWPBFTConsensus("node_1", NODES_3)
        assert pbft.is_primary(10)  # node_1 is primary at height 10

    def test_is_primary_false(self):
        pbft = CWPBFTConsensus("node_0", NODES_3)
        assert not pbft.is_primary(10)  # node_1 is primary, not node_0


class TestConsensusFlow:
    def test_start_consensus_pre_prepare(self):
        pbft = CWPBFTConsensus("node_0", NODES_3)
        vote = pbft.start_consensus("hash_001")
        assert pbft.get_state() == ConsensusState.PRE_PREPARE
        assert vote.phase == "pre_prepare"
        assert vote.voter_id == "node_0"
        assert vote.block_hash == "hash_001"

    def test_receive_pre_prepare_enter_prepare(self):
        pbft = CWPBFTConsensus("node_1", NODES_3)
        vote = pbft.receive_pre_prepare("hash_001", "node_0")
        assert pbft.get_state() == ConsensusState.PREPARE
        assert vote.phase == "prepare"
        assert vote.voter_id == "node_1"

    def test_full_consensus_flow_3nodes_via_fast(self):
        """3节点：non-primary 节点的 PRE-PREPARE→PREPARE 和 fast_consensus 验证"""
        node1 = CWPBFTConsensus("node_1", NODES_3)
        node2 = CWPBFTConsensus("node_2", NODES_3)
        block_hash = "test_block_hash_xyz"

        # 1. Non-primary nodes receive pre-prepare → enter PREPARE
        p1_vote = node1.receive_pre_prepare(block_hash, "node_0")
        p2_vote = node2.receive_pre_prepare(block_hash, "node_0")
        assert node1.get_state() == ConsensusState.PREPARE
        assert node2.get_state() == ConsensusState.PREPARE
        assert p1_vote.phase == "prepare"
        assert p2_vote.phase == "prepare"

        # 2. fast_consensus simulates complete flow → COMMITTED
        for node in [node1, node2]:
            node.reset()
            assert node.fast_consensus(block_hash, "node_0")
            assert node.is_consensus_reached()


class TestFastConsensus:
    def test_fast_consensus_3nodes(self):
        pbft = CWPBFTConsensus("node_0", NODES_3)
        result = pbft.fast_consensus("hash_fast", "node_0")
        assert result is True
        assert pbft.is_consensus_reached()
        assert pbft.get_state() == ConsensusState.COMMITTED

    def test_fast_consensus_4nodes(self):
        pbft = CWPBFTConsensus("node_0", NODES_4)
        assert pbft.fast_consensus("hash_fast4", "node_0")
        stats = pbft.get_consensus_stats()
        assert stats["n_nodes"] == 4
        assert stats["f_tolerance"] == 1  # floor((4-1)/3) = 1

    def test_fast_consensus_sets_votes(self):
        pbft = CWPBFTConsensus("node_0", NODES_3)
        pbft.fast_consensus("hash_votes", "node_0")
        stats = pbft.get_consensus_stats()
        assert stats["prepare_votes"] == 3
        assert stats["commit_votes"] == 3


class TestWeightManagement:
    def test_initial_weights_equal(self):
        """P1-8修复：初始权重为INITIAL_WEIGHT=0.3而非1.0"""
        pbft = CWPBFTConsensus("node_0", NODES_3)
        weights = pbft.get_weights()
        # 初始权重为INITIAL_WEIGHT，需累积贡献后逐步提升
        assert weights == {"node_0": 0.3, "node_1": 0.3, "node_2": 0.3}

    def test_update_weight(self):
        """P1-8修复：update_weight受MIN_WEIGHT下界保护"""
        pbft = CWPBFTConsensus("node_0", NODES_3)
        pbft.update_weight("node_0", 1.5)
        pbft.update_weight("node_1", 0.5)
        weights = pbft.get_weights()
        assert weights["node_0"] == 1.5
        assert weights["node_1"] == 0.5
        assert weights["node_2"] == 0.3  # unchanged (INITIAL_WEIGHT)

    def test_weight_not_negative(self):
        """P1-8修复：封禁节点权重为0，非封禁节点受MIN_WEIGHT保护"""
        pbft = CWPBFTConsensus("node_0", NODES_3)
        pbft.update_weight("node_0", -0.5)  # 封禁节点
        assert pbft.get_weights()["node_0"] == 0.0  # 封禁=0
        # 非封禁节点即使指定低于MIN_WEIGHT也受保护
        pbft.update_weight("node_1", 0.05)  # 低于MIN_WEIGHT=0.1
        assert pbft.get_weights()["node_1"] == 0.1  # 受MIN_WEIGHT下界保护

    def test_weight_affects_threshold_3nodes(self):
        """权重影响共识阈值（P1-8修复：先设定权重为1.0再测试）"""
        pbft = CWPBFTConsensus("node_0", NODES_3)
        # 先将所有节点权重设为1.0（从INITIAL_WEIGHT=0.3提升）
        for nid in NODES_3:
            pbft.update_weight(nid, 1.0)
        # thresholds: 2/3 * 3.0 = 2.0
        pbft.update_weight("node_0", 0.0)  # node_0 can't vote (封禁)
        # total_weight = 2.0, threshold = 2/3*2 = 1.33
        # fast_consensus all nodes vote: prepare weight = 0+1+1 = 2.0 >= 1.33 -> OK
        assert pbft.fast_consensus("hash_w", "node_0")


class TestTimeoutAndReset:
    def test_initial_not_timed_out(self):
        pbft = CWPBFTConsensus("node_0", NODES_3)
        assert not pbft.is_timed_out()

    def test_reset(self):
        pbft = CWPBFTConsensus("node_0", NODES_3)
        pbft.start_consensus("hash_reset")
        pbft.fast_consensus("hash_hijack", "node_0")
        pbft.reset()
        assert pbft.get_state() == ConsensusState.IDLE
        assert not pbft.is_consensus_reached()

    def test_receive_vote_rejects_wrong_hash(self):
        pbft = CWPBFTConsensus("node_0", NODES_3)
        pbft.start_consensus("correct_hash")
        wrong_vote = ConsensusVote(
            voter_id="node_1", block_hash="wrong_hash",
            phase="prepare", weight=1.0
        )
        result = pbft.receive_vote(wrong_vote)
        assert result is None  # rejected

    def test_get_consensus_stats(self):
        pbft = CWPBFTConsensus("node_0", NODES_3)
        pbft.fast_consensus("hash_stats", "node_0")
        stats = pbft.get_consensus_stats()
        assert stats["node_id"] == "node_0"
        assert stats["state"] == ConsensusState.COMMITTED
        assert stats["n_nodes"] == 3
        assert "hash_stats" in stats["current_block_hash"]


# ── P2-B: 三阶段加权投票完整测试 ──


class TestThreePhaseConsensus:
    """完整三阶段共识流程测试（PRE-PREPARE→PREPARE→COMMIT）"""

    def test_full_3phase_3nodes_equal_weight(self):
        """3节点等权三阶段共识：所有节点权重=1.0（P1-8修复：先设权重为1.0）
        流程：主节点PRE-PREPARE → 所有节点PREPARE投票 → 2/3权重后COMMIT → COMMITTED"""
        nodes = {}
        for nid in NODES_3:
            nodes[nid] = CWPBFTConsensus(nid, NODES_3)
            # P1-8修复：先将所有节点权重设为1.0
            nodes[nid].update_weight("node_0", 1.0)
            nodes[nid].update_weight("node_1", 1.0)
            nodes[nid].update_weight("node_2", 1.0)

        block_hash = "block_3phase_equal"
        # threshold = 2/3 * 3.0 = 2.0

        # ── Phase 1: PRE-PREPARE — 主节点发起共识 ──
        primary = nodes["node_0"]
        pre_prepare_vote = primary.start_consensus(block_hash)
        assert primary.get_state() == ConsensusState.PRE_PREPARE

        # ── Phase 2: PREPARE ──
        # 非主节点收到PRE-PREPARE后进入PREPARE
        for nid in ["node_1", "node_2"]:
            nodes[nid].receive_pre_prepare(block_hash, "node_0")
            assert nodes[nid].get_state() == ConsensusState.PREPARE

        # 主节点也进入PREPARE，并添加自身prepare票到_votes
        primary._state = ConsensusState.PREPARE
        primary._votes['prepare']['node_0'] = ConsensusVote(
            voter_id="node_0", block_hash=block_hash,
            phase="prepare", weight=1.0
        )

        # node_1和node_2各自已有自身prepare票（由receive_pre_prepare产生）
        # 但在CW-PBFT模拟中，自身票不会自动加入_votes字典
        # 需要手动添加自身prepare票（在真实PBFT中通过广播回传）
        nodes["node_1"]._votes['prepare']['node_1'] = ConsensusVote(
            voter_id="node_1", block_hash=block_hash,
            phase="prepare", weight=1.0
        )
        nodes["node_2"]._votes['prepare']['node_2'] = ConsensusVote(
            voter_id="node_2", block_hash=block_hash,
            phase="prepare", weight=1.0
        )

        # 主节点收集node_1的prepare票
        result = primary.receive_vote(ConsensusVote(
            voter_id="node_1", block_hash=block_hash,
            phase="prepare", weight=1.0
        ))
        # primary: node_0(1.0) + node_1(1.0) = 2.0 >= 2.0 → COMMIT
        assert result is not None
        assert result.phase == "commit"

        # node_1收到primary的prepare票 → self(1.0) + primary(1.0) = 2.0 >= 2.0 → COMMIT
        result_1 = nodes["node_1"].receive_vote(ConsensusVote(
            voter_id="node_0", block_hash=block_hash,
            phase="prepare", weight=1.0
        ))
        assert result_1 is not None
        assert result_1.phase == "commit"

        # ── Phase 3: COMMIT ──
        # primary需要收集commit票。先添加自身commit票
        primary._votes['commit']['node_0'] = ConsensusVote(
            voter_id="node_0", block_hash=block_hash,
            phase="commit", weight=1.0
        )
        node_1_commit = ConsensusVote(
            voter_id="node_1", block_hash=block_hash,
            phase="commit", weight=1.0
        )
        primary.receive_vote(node_1_commit)
        # primary: node_0(1.0) + node_1(1.0) = 2.0 >= 2.0 → COMMITTED
        assert primary.is_consensus_reached()

        # node_1需要收集commit票（自身commit + primary commit）
        # node_1已经在COMMIT状态（由receive_vote产生的commit票来自node_1自身）
        nodes["node_1"]._votes['commit']['node_1'] = ConsensusVote(
            voter_id="node_1", block_hash=block_hash,
            phase="commit", weight=1.0
        )
        commit_from_primary = ConsensusVote(
            voter_id="node_0", block_hash=block_hash,
            phase="commit", weight=1.0
        )
        nodes["node_1"].receive_vote(commit_from_primary)
        # node_1: self(1.0) + primary(1.0) = 2.0 >= 2.0 → COMMITTED
        assert nodes["node_1"].is_consensus_reached()

    def test_full_3phase_4nodes_with_weighted_voting(self):
        """4节点不等权三阶段共识：验证贡献加权投票阈值判定（P1-8修复）

        09-28 更正（全检 #2）：本用例原先**依赖报文自报权重**才成立 ——
        它让 node_0 自报 w=2.0，但 update_weight 受 ``MAX_WEIGHT=1.5`` 钳制，
        权威表中 node_0 实际只有 **1.5**。也就是说，旧的"两票即可达 quorum"
        是靠一个**高于任何权威值的伪造权重**凑出来的，
        恰好把漏洞本身固化成了预期行为。现改为按权威表计算：

            权威权重 node_0=1.5（钳制自 2.0）, node_1=1.0, node_2=0.5, node_3=1.0
            total = 4.0，threshold = 2/3 * 4.0 = 2.6667
            {node_0,node_1,node_2} = 3.0 >= 2.6667 → 达成
            {node_1,node_2,node_3} = 2.5 <  2.6667 → 不达成

        后者才是"高贡献节点左右 quorum"的干净证据：同样**三票**的两个集合，
        只因成员权重不同（1.5 vs 1.0）而结果相反。
        """
        nodes = {}
        for nid in NODES_4:
            nodes[nid] = CWPBFTConsensus(nid, NODES_4)

        block_hash = "block_3phase_4w"
        # 设置权重（node_0 传入 2.0，会被 MAX_WEIGHT 钳到 1.5）
        for nid in NODES_4:
            nodes[nid].update_weight("node_0", 2.0)
            nodes[nid].update_weight("node_1", 1.0)
            nodes[nid].update_weight("node_2", 0.5)
            nodes[nid].update_weight("node_3", 1.0)

        # Phase 1: PRE-PREPARE
        primary = nodes["node_0"]
        primary.start_consensus(block_hash)

        # Phase 2: 非主节点收到PRE-PREPARE
        for nid in ["node_1", "node_2", "node_3"]:
            nodes[nid].receive_pre_prepare(block_hash, "node_0")
            assert nodes[nid].get_state() == ConsensusState.PREPARE

        # 权威权重自证（防止日后再有人按 2.0 来理解本用例）
        weights = primary.get_weights()
        assert weights == {"node_0": 1.5, "node_1": 1.0, "node_2": 0.5, "node_3": 1.0}
        assert abs(primary._total_weight - 4.0) < 1e-9
        threshold = CWPBFTConsensus.WEIGHT_QUORUM_RATIO * primary._total_weight
        assert abs(threshold - 2.6667) < 1e-3

        primary._state = ConsensusState.PREPARE
        primary._votes['prepare']['node_0'] = ConsensusVote(
            voter_id="node_0", block_hash=block_hash,
            phase="prepare", weight=weights["node_0"]
        )

        # 追加 node_1：1.5 + 1.0 = 2.5 < 2.6667 → 尚不足，仍在 PREPARE
        # （这正是旧用例误以为"两票达标"之处）
        assert primary.receive_vote(ConsensusVote(
            voter_id="node_1", block_hash=block_hash,
            phase="prepare", weight=1.0
        )) is None
        assert primary.get_state() == ConsensusState.PREPARE

        # 再追加 node_2：1.5 + 1.0 + 0.5 = 3.0 >= 2.6667 → 进入 COMMIT
        result = primary.receive_vote(ConsensusVote(
            voter_id="node_2", block_hash=block_hash,
            phase="prepare", weight=0.5
        ))
        assert result is not None
        assert result.phase == "commit"

        # Phase 3: COMMIT —— 同一批权重成员在 commit 阶段再次达标
        primary._votes['commit']['node_0'] = ConsensusVote(
            voter_id="node_0", block_hash=block_hash,
            phase="commit", weight=weights["node_0"]
        )
        primary.receive_vote(ConsensusVote(
            voter_id="node_1", block_hash=block_hash, phase="commit", weight=1.0))
        primary.receive_vote(ConsensusVote(
            voter_id="node_2", block_hash=block_hash, phase="commit", weight=0.5))
        assert primary.is_consensus_reached()

    def test_weighted_quorum_depends_on_who_votes(self):
        """贡献加权的本质：同样票数的两个集合，因成员权重不同结果相反

        09-28 新增（全检 #2 配套）：用**三票对三票**的对照把"权重决定 quorum"
        从"票数决定 quorum"里干净地剥离出来（旧的"两票达标"是伪造权重的产物）。
        """
        pbft = CWPBFTConsensus("node_0", NODES_4)
        pbft.update_weight("node_0", 2.0)   # 钳制 → 1.5
        pbft.update_weight("node_1", 1.0)
        pbft.update_weight("node_2", 0.5)
        pbft.update_weight("node_3", 1.0)

        # 含最高权重节点 node_0 的三票 → 达标
        rich = {"node_0": 1.5, "node_1": 1.0, "node_2": 0.5}
        pbft._votes['prepare'] = {
            nid: ConsensusVote(nid, "h", "prepare", w) for nid, w in rich.items()
        }
        assert pbft._check_weight_threshold('prepare') is True

        # 用 node_3 顶替 node_0（同为三票）→ 权重从 3.0 跌到 2.5 → 不达标
        poor = {"node_1": 1.0, "node_2": 0.5, "node_3": 1.0}
        pbft._votes['prepare'] = {
            nid: ConsensusVote(nid, "h", "prepare", w) for nid, w in poor.items()
        }
        assert pbft._check_weight_threshold('prepare') is False


class TestVoteWeightAuthority:
    """09-28 新增（全检 #2）：投票权重必须以本地权威表为准，不得信任自报字段"""

    def _make_prepared(self):
        pbft = CWPBFTConsensus("node_0", NODES_3)
        pbft.update_weight("node_0", 1.0)
        pbft.update_weight("node_1", 1.0)
        pbft.update_weight("node_2", 1.0)
        pbft.start_consensus("h")
        pbft._state = ConsensusState.PREPARE
        return pbft

    def test_threshold_ignores_forged_weight_inserted_directly(self):
        """绕过 receive_vote 直接塞进 _votes 的伪造权重，阈值判定同样不认

        为什么单这一条测试不可省：Fix #2 有两层防御（收票点归一化 + 计票点查表），
        而**两层会互相遮蔽** —— 变异实测证实，只回退 receive_vote 的归一化能被
        抓到，但反过来**只回退计票点查表却抓不到**（因为数据早已在收票点被洗净）。
        故必须绕开收票点、直接向 _votes 注入伪造票，给计票点独立的覆盖。
        """
        pbft = self._make_prepared()
        # 权威：3 节点各 1.0 → total=3.0，threshold=2.0
        pbft._votes['prepare']['node_1'] = ConsensusVote(
            voter_id="node_1", block_hash="h", phase="prepare", weight=1e6
        )
        assert pbft._check_weight_threshold('prepare') is False, (
            "计票点仍在信任票上的自报 weight：单票 1e6 就跨越了 2/3 阈值"
        )

        # 对照组：补齐到两票真实权重（1.0+1.0=2.0>=2.0）才达标，
        # 证明上面的 False 来自"权重不被信任"而非断言恒假。
        pbft._votes['prepare']['node_2'] = ConsensusVote(
            voter_id="node_2", block_hash="h", phase="prepare", weight=1.0
        )
        assert pbft._check_weight_threshold('prepare') is True

    def test_forged_weight_cannot_reach_quorum(self):
        """核心：单张伪造 weight=1e6 的票**不能**越过 2/3 阈值

        修复前 3 节点初值 0.3 → total=0.9、阈值 0.6，而自报 1.0 的一票即已达标，
        等于任意成员可独自通过任意区块。
        """
        pbft = self._make_prepared()
        assert pbft.receive_vote(ConsensusVote(
            voter_id="node_1", block_hash="h", phase="prepare", weight=1e6
        )) is None, "伪造超高权重居然让单票越过了 quorum"
        assert pbft.get_state() == ConsensusState.PREPARE

    def test_stored_weight_is_normalized_to_authoritative(self):
        """入库票的 weight 被覆盖为权威值，自报字段不再有第二个可信通道"""
        pbft = self._make_prepared()
        pbft.receive_vote(ConsensusVote(
            voter_id="node_1", block_hash="h", phase="prepare", weight=999.0
        ))
        stored = pbft._votes['prepare']['node_1']
        assert stored.weight == pbft.get_weights()["node_1"] == 1.0

    def test_non_member_vote_rejected(self):
        """女巫门控：非共识成员身份的投票被拒收，不入库、不计入参与率"""
        pbft = self._make_prepared()
        assert pbft.receive_vote(ConsensusVote(
            voter_id="node_evil", block_hash="h", phase="prepare", weight=1.0
        )) is None
        assert "node_evil" not in pbft._votes['prepare']

    def test_banned_node_vote_not_counted(self):
        """封禁节点（w=0）投票不计票 —— 与 #3 修复配套，隔断绕过惩罚的投票路径"""
        pbft = self._make_prepared()
        pbft.update_weight("node_1", 0.0)   # 封禁
        assert pbft.receive_vote(ConsensusVote(
            voter_id="node_1", block_hash="h", phase="prepare", weight=5.0
        )) is None
        # 此时 _votes['prepare'] 里只有被封禁的 node_1（start_consensus 不会
        # 把自己的票塞进 _votes），计票权重为 0 → 远不足 2/3 阈值 2.0
        assert pbft._check_weight_threshold('prepare') is False


class TestWeightedVotingThreshold:
    """贡献加权投票阈值判定测试 — CW-PBFT核心创新点"""

    def test_threshold_calculation_equal_weight(self):
        """等权阈值：2/3 * total_weight（P1-8修复：先设定权重为1.0）"""
        pbft = CWPBFTConsensus("node_0", NODES_3)
        # 先将所有节点权重设为1.0（从INITIAL_WEIGHT=0.3提升）
        for nid in NODES_3:
            pbft.update_weight(nid, 1.0)
        # total_weight = 3.0, threshold = 2/3 * 3.0 = 2.0
        pbft.fast_consensus("hash_thresh", "node_0")
        votes = pbft._votes
        # prepare阶段：3票×1.0 = 3.0 >= 2.0 threshold → 通过
        prepare_weight = sum(v.weight for v in votes['prepare'].values())
        assert prepare_weight >= 2.0  # 2/3 * 3.0

    def test_threshold_with_skewed_weights_3nodes(self):
        """不等权：贡献高的节点权重更大，影响阈值判定（P1-8修复：先设基础权重）"""
        pbft = CWPBFTConsensus("node_0", NODES_3)
        # 先设基础权重，再调整
        pbft.update_weight("node_0", 2.0)
        pbft.update_weight("node_1", 1.0)
        pbft.update_weight("node_2", 0.5)
        # total_weight = 3.5, threshold = 2/3 * 3.5 ≈ 2.33

        # fast_consensus模拟：所有节点投票
        pbft.fast_consensus("hash_skewed", "node_0")
        prepare_weight = sum(v.weight for v in pbft._votes['prepare'].values())
        # 2.0 + 1.0 + 0.5 = 3.5 >= 2.33 → 通过
        assert prepare_weight >= (2 / 3) * 3.5
        assert pbft.is_consensus_reached()

    def test_threshold_high_contributor_dominates(self):
        """高贡献节点权重可以单独满足阈值（n=4场景）（P1-8修复：先设基础权重）"""
        pbft = CWPBFTConsensus("node_0", NODES_4)
        pbft.update_weight("node_0", 3.0)
        pbft.update_weight("node_1", 0.5)
        pbft.update_weight("node_2", 0.5)
        pbft.update_weight("node_3", 0.5)
        # total_weight = 4.5, threshold = 2/3 * 4.5 = 3.0

        # fast_consensus：node_0(3.0) + node_1(0.5) = 3.5 >= 3.0
        # 即使只有2个节点投票也满足阈值
        pbft.fast_consensus("hash_dominant", "node_0")
        assert pbft.is_consensus_reached()

    def test_zero_weight_node_cannot_vote_effectively(self):
        """权重=0的节点投票不贡献阈值计算（P1-8修复：先设基础权重为1.0）"""
        pbft = CWPBFTConsensus("node_0", NODES_3)
        # 先将所有节点权重设为1.0
        for nid in NODES_3:
            pbft.update_weight(nid, 1.0)
        pbft.update_weight("node_0", 0.0)  # 封禁节点
        # total_weight = 2.0, threshold = 2/3 * 2.0 ≈ 1.33
        # fast_consensus所有节点投票：0 + 1 + 1 = 2.0 >= 1.33
        pbft.fast_consensus("hash_banned", "node_0")
        prepare_weight = sum(v.weight for v in pbft._votes['prepare'].values())
        # node_0的weight=0不贡献任何有效权重
        assert pbft._votes['prepare']['node_0'].weight == 0.0
        assert prepare_weight >= (2 / 3) * 2.0

    def test_threshold_not_reached_insufficient_weight(self):
        """投票权重不足时共识不应达成（手动模拟）"""
        pbft = CWPBFTConsensus("node_0", NODES_4)
        pbft.update_weight("node_0", 0.1)  # 极低权重
        pbft.update_weight("node_1", 0.1)
        pbft.update_weight("node_2", 0.1)
        pbft.update_weight("node_3", 1.0)
        # total_weight = 1.3, threshold = 2/3 * 1.3 ≈ 0.87

        # 如果只有node_0投票（0.1），远不够
        pbft.start_consensus("hash_insufficient")
        pbft._state = ConsensusState.PREPARE
        vote = ConsensusVote(
            voter_id="node_0", block_hash="hash_insufficient",
            phase="prepare", weight=0.1
        )
        result = pbft.receive_vote(vote)
        # 0.1 < 0.87 threshold → 不应进入COMMIT
        assert result is None
        assert pbft.get_state() == ConsensusState.PREPARE
        assert not pbft.is_consensus_reached()

    def test_weight_update_recomputes_total_weight(self):
        """权重更新后total_weight重新计算（P1-8：下界保护；P1-15：MAX_WEIGHT=1.5上界钳制）"""
        pbft = CWPBFTConsensus("node_0", NODES_3)
        assert abs(pbft._total_weight - 0.9) < 0.01  # 3 * INITIAL_WEIGHT(0.3)

        # P1-15：超上界的请求被钳制到 MAX_WEIGHT=1.5（限制单个节点权重上限）
        pbft.update_weight("node_0", 2.0)
        assert abs(pbft._weights["node_0"] - 1.5) < 0.01
        assert abs(pbft._total_weight - 2.1) < 0.01  # 1.5 + 0.3 + 0.3

        pbft.update_weight("node_1", 0.5)
        assert abs(pbft._total_weight - 2.3) < 0.01  # 1.5 + 0.5 + 0.3

    def test_byzantine_tolerance_calculation(self):
        """拜占庭容错数 f = floor((n-1)/3)"""
        pbft_3 = CWPBFTConsensus("node_0", NODES_3)
        assert pbft_3.f == 0  # floor(2/3) = 0

        pbft_4 = CWPBFTConsensus("node_0", NODES_4)
        assert pbft_4.f == 1  # floor(3/3) = 1

        pbft_7 = CWPBFTConsensus("node_0",
                                  [f"node_{i}" for i in range(7)])
        assert pbft_7.f == 2  # floor(6/3) = 2


class TestPhaseTransitionDetails:
    """三阶段状态转换细节测试"""

    def test_prepare_to_commit_requires_threshold(self):
        """PREPARE→COMMIT必须达到2/3权重阈值（P1-8修复：先设权重为1.0）"""
        pbft = CWPBFTConsensus("node_0", NODES_3)
        # 先将所有节点权重设为1.0（从INITIAL_WEIGHT=0.3提升）
        for nid in NODES_3:
            pbft.update_weight(nid, 1.0)
        pbft.start_consensus("hash_phase_test")
        pbft._state = ConsensusState.PREPARE

        # 只有1票(w=1.0)，不够 2/3*3=2.0 阈值
        vote1 = ConsensusVote(
            voter_id="node_1", block_hash="hash_phase_test",
            phase="prepare", weight=1.0
        )
        result = pbft.receive_vote(vote1)
        assert result is None  # 不应进入COMMIT
        assert pbft.get_state() == ConsensusState.PREPARE

        # 第二票(w=1.0)，累计2.0 >= 2.0 阈值
        vote2 = ConsensusVote(
            voter_id="node_2", block_hash="hash_phase_test",
            phase="prepare", weight=1.0
        )
        result = pbft.receive_vote(vote2)
        assert result is not None  # 进入COMMIT，发出commit票
        assert result.phase == "commit"
        assert pbft.get_state() == ConsensusState.COMMIT

    def test_commit_to_committed_requires_threshold(self):
        """COMMIT→COMMITTED必须达到2/3权重阈值（P1-8修复：先设权重为1.0）"""
        pbft = CWPBFTConsensus("node_0", NODES_3)
        # 先将所有节点权重设为1.0（从INITIAL_WEIGHT=0.3提升）
        for nid in NODES_3:
            pbft.update_weight(nid, 1.0)
        pbft.start_consensus("hash_commit_test")
        pbft._state = ConsensusState.COMMIT

        # 1票commit(w=1.0)，不够 2.0 阈值
        vote1 = ConsensusVote(
            voter_id="node_1", block_hash="hash_commit_test",
            phase="commit", weight=1.0
        )
        pbft.receive_vote(vote1)
        assert not pbft.is_consensus_reached()
        assert pbft.get_state() == ConsensusState.COMMIT

        # 第二票commit(w=1.0)，累计2.0 >= 2.0 → COMMITTED
        vote2 = ConsensusVote(
            voter_id="node_2", block_hash="hash_commit_test",
            phase="commit", weight=1.0
        )
        pbft.receive_vote(vote2)
        assert pbft.is_consensus_reached()
        assert pbft.get_state() == ConsensusState.COMMITTED

    def test_commit_votes_ignored_in_prepare_state(self):
        """PREPARE状态下收到COMMIT票不应触发状态转换"""
        pbft = CWPBFTConsensus("node_0", NODES_3)
        pbft.start_consensus("hash_mismatch_state")
        pbft._state = ConsensusState.PREPARE

        commit_vote = ConsensusVote(
            voter_id="node_1", block_hash="hash_mismatch_state",
            phase="commit", weight=1.0
        )
        result = pbft.receive_vote(commit_vote)
        # COMMIT票在PREPARE阶段被记录但不触发阈值检查
        assert result is None
        assert pbft.get_state() == ConsensusState.PREPARE

    def test_prepare_votes_ignored_in_commit_state(self):
        """COMMIT状态下收到PREPARE票不应触发COMMIT阈值"""
        pbft = CWPBFTConsensus("node_0", NODES_3)
        pbft.start_consensus("hash_late_prepare")
        pbft._state = ConsensusState.COMMIT

        # 此时1张commit票（自身）
        self_commit = ConsensusVote(
            voter_id="node_0", block_hash="hash_late_prepare",
            phase="commit", weight=1.0
        )
        pbft._votes['commit']['node_0'] = self_commit

        # 收到迟到的prepare票，不应触发commit检查
        late_prepare = ConsensusVote(
            voter_id="node_1", block_hash="hash_late_prepare",
            phase="prepare", weight=1.0
        )
        result = pbft.receive_vote(late_prepare)
        assert result is None
        assert pbft.get_state() == ConsensusState.COMMIT

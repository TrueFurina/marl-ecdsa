"""
网络版 CW-PBFT 共识引擎
通过真实 P2P 网络（asyncio TCP）传递共识消息，实现真正的分布式三阶段共识

P1-7修复：投票广播附加ECDSA签名+验证
- _broadcast_vote()：发送投票前用私钥对投票数据签名
- _on_prepare()和_on_commit()：收到投票后验证签名，确认voter_id与签名公钥绑定

Architecture：
  ConsensusNode = P2PNode + CWPBFTConsensus + asyncio event loop
  每个 ConsensusNode 运行在独立线程的 event loop 上
  主线程通过 run_coroutine_threadsafe 触发异步操作
"""
import asyncio
import hashlib
import json
import logging
import threading
import time
from typing import Dict, List, Optional, Callable, Tuple

from .p2p_node import P2PNode
from .message_protocol import MessageProtocol, MessageType
from ..consensus.cw_pbft import ConsensusVote, ConsensusState
from ..consensus.factory import create_consensus_engine

logger = logging.getLogger(__name__)


class NetworkConsensusNode:
    """
    真实网络共识节点
    P2P 节点 + 共识引擎（CW-PBFT/标准PBFT/快速）的完整组合
    """

    def __init__(
        self,
        node_id: str,
        host: str,
        port: int,
        all_node_ids: List[str],
        key_manager=None,  # P1-7修复：注入KeyManager用于投票签名
        consensus_mode: str = None,  # cw_pbft / standard_pbft / fast，None时读config.json
        allow_insecure_vote: bool = False,  # BUG2: 仅连通性测试显式开启投票宽松兜底
        allow_insecure_register: bool = False,  # BUG1: 透传给 P2PNode
        enable_tls: bool = True,  # BUG4: 透传给 P2PNode（默认开启）
        tls_dir: str = "keys/tls",  # BUG4: 透传给 P2PNode
        use_batch_async_verify: bool = False,  # 共识投票批量异步验签 offload 开关（默认关闭；开启=needs-design 批量热路径改造，须全面回归）
        batch_verify_threshold: int = 16,  # 批量 flush 阈值（缓冲达此值即内联批量验签）
        batch_verify_flush_timeout: float = 0.002,  # 批量 flush 定时器超时（秒）
        use_async_verify: bool = False,  # 共识投票验签异步 offload 开关（默认关闭；开启=needs-design 接入，须全面回归）
    ):
        self.node_id = node_id
        self.host = host
        self.port = port
        self.all_node_ids = all_node_ids
        self.key_manager = key_manager  # P1-7修复：密钥管理器引用
        self.consensus_mode = consensus_mode
        # BUG2 修复：投票签名默认 fail-closed（生产必须配 key_manager）
        self._allow_insecure_vote = allow_insecure_vote
        # 共识验签异步 offload 开关：默认 False = 走原同步 _verify_vote_signature（行为逐字一致）；
        # 开启后三处共识处理器改走 _verify_vote_signature_async（await verify_cached_async，offload 出 event loop）。
        self._use_async_verify = use_async_verify
        # 共识投票批量异步验签 offload 开关：默认 False = 不进入批量分支（_verify_vote_signature_auto
        # 行为与历史逐字一致）；开启后按 (block_height, phase) 缓冲投票，达阈值/超时后一次
        # verify_batch_async 批量 offload。fail-safe：批量异常整批回退逐票同步，绝不漏检伪造票。
        self._use_batch_async_verify = use_batch_async_verify
        self._batch_threshold = batch_verify_threshold
        self._batch_flush_timeout = batch_verify_flush_timeout
        # 批量验签缓冲：键=(block_height, phase) -> 列表[(data, voter_id, asyncio.Future)]
        self._verify_batches: Dict = {}
        self._verify_batch_timers: Dict = {}

        # P2P 底层通信（P1-9修复：传递key_manager给P2PNode；BUG1/BUG4 透传）
        self.p2p = P2PNode(
            node_id, host, port, is_consensus_node=True,
            key_manager=key_manager,
            allow_insecure_register=allow_insecure_register,
            enable_tls=enable_tls,
            tls_dir=tls_dir,
        )
        # 共识引擎（工厂创建，支持模式切换）
        self.cw_pbft = create_consensus_engine(node_id, all_node_ids, mode=consensus_mode)

        # asyncio event loop（专用线程）
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()

        # 共识完成通知
        self._consensus_done = threading.Event()
        self._consensus_result: Optional[bool] = None

        # B3修复：共识状态跨线程锁，保护 _state/_votes/_current_block_hash
        # 主线程 propose_consensus 与 P2P 事件循环 _on_prepare/_on_commit 并发访问
        self._consensus_lock = threading.RLock()

        # 消息计数
        self.msg_sent = 0
        self.msg_received = 0
        self.consensus_rounds = 0

        # FT-FIX(2026-10-13)：跨连接消息乱序容错。
        # 副本A的PREPARE可能先于主节点的PRE-PREPARE到达副本B（不同TCP连接到达顺序不可控），
        # 旧实现直接丢弃导致压线容错场景丢票、共识超时。现改为缓存到 pending 队列，
        # 待 _current_block_hash 就绪（收到 PRE-PREPARE）后 flush 处理。
        self._pending_prepares: List[Tuple["ConsensusVote", int]] = []
        self._round_height: Optional[int] = None  # F13：当前轮高度绑定

        # 注册共识消息处理器
        self.p2p.register_handler(MessageType.CONSENSUS_PREPREPARE, self._on_preprepare)
        self.p2p.register_handler(MessageType.CONSENSUS_PREPARE, self._on_prepare)
        self.p2p.register_handler(MessageType.CONSENSUS_COMMIT, self._on_commit)

    # -------------------------------------------------------------------------
    # 启动 / 停止
    # -------------------------------------------------------------------------

    def start(self):
        """在独立线程启动 asyncio event loop 和 P2P 节点"""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name=f"p2p-{self.node_id}"
        )
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise RuntimeError(f"P2P节点 {self.node_id} 启动超时或失败")

    def _run_loop(self):
        """event loop 线程入口"""
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._async_start())

    async def _async_start(self):
        await self.p2p.start()
        self._ready.set()
        # 永久运行，等待外部 stop()
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    def stop(self):
        """停止节点"""
        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self.p2p.stop(), self._loop)
            future.result(timeout=3)

    def clear_msg_cache(self):
        """安全清除消息去重缓存（通过 event loop，避免线程冲突）"""
        if self._loop and self._loop.is_running():
            async def _clear():
                self.p2p._seen_msg_ids.clear()
            future = asyncio.run_coroutine_threadsafe(_clear(), self._loop)
            future.result(timeout=2)

    # -------------------------------------------------------------------------
    # 连接到其他节点
    # -------------------------------------------------------------------------

    def connect_to(self, target_node_id: str, host: str, port: int) -> bool:
        """主动连接到另一个节点（同步阻塞调用），返回连接是否成功。"""
        future = asyncio.run_coroutine_threadsafe(
            self.p2p.connect_to(host, port, target_node_id),
            self._loop
        )
        return bool(future.result(timeout=5))

    # -------------------------------------------------------------------------
    # 发起共识（供主节点调用）
    # -------------------------------------------------------------------------

    def propose_consensus(self, block_hash: str, block_height: int, timeout: float = 3.0) -> bool:
        """
        主节点发起一轮共识（CW-PBFT/标准PBFT/快速模式）
        广播 PRE-PREPARE → 收集 PREPARE + COMMIT → 共识完成
        :param block_height: 本轮区块高度（F13：进签名体并做主节点轮换校验）
        :return: 是否达成共识
        """
        self._consensus_done.clear()
        self._consensus_result = None
        self.consensus_rounds += 1
        self._round_height = int(block_height)

        # fast 模式：单轮确认，跳过网络三阶段与权重阈值（性能演示）
        if self.consensus_mode == 'fast':
            ok = self.cw_pbft.fast_consensus(block_hash, self.node_id)
            self._consensus_result = bool(ok)
            self._consensus_done.set()
            logger.info(f"[NetConsensus] {self.node_id} fast模式快速共识: {block_hash[:16]}... -> {ok}")
            return ok

        # 主节点发起 PRE-PREPARE，进入 PRE_PREPARE 状态
        vote = self.cw_pbft.start_consensus(block_hash)

        # 主节点自己也进入 PREPARE 状态并构造 PREPARE 票
        from ..consensus.cw_pbft import ConsensusVote as _CV, ConsensusState as _CS
        # B3修复：临界区加锁，防止与 _on_prepare/_on_commit 并发竞态
        with self._consensus_lock:
            self.cw_pbft._state = _CS.PREPARE
            prepare_vote = _CV(
                voter_id=self.node_id,
                block_hash=block_hash,
                phase='prepare',
                weight=self.cw_pbft._weights.get(self.node_id, 1.0),
            )
            # 主节点把自己的 prepare 票加到投票池（必须在广播前完成，避免线程竞争）
            self.cw_pbft._votes['prepare'][self.node_id] = prepare_vote

        # 一次性异步广播 PRE-PREPARE + PREPARE（确保本地票已就位后再发消息）
        async def _broadcast_both():
            await self._broadcast_vote(MessageType.CONSENSUS_PREPREPARE, vote, block_height=block_height)
            await self._broadcast_vote(MessageType.CONSENSUS_PREPARE, prepare_vote, block_height=block_height)

        future = asyncio.run_coroutine_threadsafe(_broadcast_both(), self._loop)
        future.result(timeout=3)
        logger.info(f"[NetConsensus] {self.node_id} 广播 PRE-PREPARE: {block_hash[:16]}...")

        # 等待共识完成（_on_commit 里会 set _consensus_done）
        reached = self._consensus_done.wait(timeout=timeout)
        return reached and bool(self._consensus_result)

    # -------------------------------------------------------------------------
    # 消息处理器（异步，运行在 P2P 线程的 event loop）
    # -------------------------------------------------------------------------

    def _process_prepare_vote(self, vote: "ConsensusVote") -> Tuple[Optional["ConsensusVote"], bool]:
        """PREPARE 投票核心处理（锁内调用）：hash 校验 + 状态推进 + 阈值检查。
        返回 (commit_vote, consensus_complete)；广播由调用方在锁外执行。
        FT-FIX(2026-10-13)：从 _on_prepare 提取，供即时处理与 pending flush 复用。
        """
        # 严格校验：_current_block_hash 必须已由 start_consensus/receive_pre_prepare 设置
        # 不再从投票消息自动设置——防止上轮残留消息污染哈希
        if self.cw_pbft._current_block_hash is None:
            return None, False
        if vote.block_hash != self.cw_pbft._current_block_hash:
            logger.warning(f"[NetConsensus] {self.node_id} 丢弃 PREPARE：hash 不匹配 "
                          f"({vote.block_hash[:8]} vs {self.cw_pbft._current_block_hash[:8]})")
            return None, False

        # 确保当前节点至少进入 PREPARE 状态（只向前推进，不回退）
        from ..consensus.cw_pbft import ConsensusState as _CS
        # 修复（网络层状态回退）：原实现 `if _state != COMMITTED: _state = PREPARE`
        # 会把已进入 COMMIT 的节点打回 PREPARE——随后 COMMIT 阶段的状态约束
        # (见 _on_commit: 要求 state in (COMMIT, COMMITTED)) 会拒收合法 COMMIT 票，
        # 节点需重新凑 prepare 阈值，特定乱序/重放时序下造成活性抖动，影响共识
        # 时延/成功率可复现性。改为单向推进：仅从 IDLE/PRE_PREPARE 提升到 PREPARE，
        # 已在 PREPARE/COMMIT/COMMITTED 的节点保持不变。
        if self.cw_pbft._state in (_CS.IDLE, _CS.PRE_PREPARE):
            self.cw_pbft._state = _CS.PREPARE

        commit_vote = self.cw_pbft.receive_vote(vote)
        if commit_vote:
            # 达到 2/3 权重阈值：
            # 1. 把自己的 COMMIT 加进自己的投票池（本地直接计入，不走网络去重）
            self.cw_pbft._votes['commit'][self.node_id] = commit_vote
            # 2. 本节点也立即检查是否因本次 commit 达到阈值（短路：本地不走 _on_commit）
            self.cw_pbft._state = _CS.COMMIT
            consensus_complete = False
            if self.cw_pbft._check_weight_threshold('commit'):
                self.cw_pbft._state = _CS.COMMITTED
                self._consensus_result = True
                self._consensus_done.set()
                consensus_complete = True
            return commit_vote, consensus_complete
        return None, False

    async def _on_preprepare(self, msg: Dict, from_node: str):
        """收到 PRE-PREPARE：验证后广播自己的 PREPARE"""
        self.msg_received += 1
        data = MessageProtocol.get_data(msg)
        block_hash = data.get("block_hash", "")
        primary_id = data.get("voter_id", from_node)
        block_height = data.get("block_height")

        # P0修复（2026-10-15）：PRE-PREPARE 也必须验签，与 _on_prepare/_on_commit 同口径。
        # 此前唯独本 handler 缺校验：伪造报文可触发下方 reset() 抹掉已达成的
        # COMMITTED 状态，构成活性攻击（测试 test_preprepare_auth.py 的守护意图）。
        if not await self._verify_vote_signature_auto(data, primary_id):
            logger.warning(f"[NetConsensus] {self.node_id} 丢弃 PRE-PREPARE：签名验证失败 from {primary_id}")
            return

        # P0修复（2026-10-15）：B2 女巫门控——声称的主节点必须是已知共识成员。
        # 与 cw_pbft.receive_vote 同口径（`vote.voter_id not in self._weights` 拒收），
        # 隔离 B1 验签门单独测试：insecure 模式下无签名可放行，但非成员身份仍须挡下。
        if primary_id not in self.cw_pbft._weights:
            logger.warning(f"[NetConsensus] {self.node_id} 丢弃 PRE-PREPARE：主节点 {primary_id} 非共识成员")
            return

        # F13（2026-11-02 赛后）：主节点合法性校验——block_height 必须在签名体内，
        # 且声称的主节点必须等于 get_primary(block_height) 的轮换结果。
        # 此前签名体不含高度 ⇒ 任何成员都能冒充任意轮的主节点（S6 登记残留）。
        if not isinstance(block_height, int) or isinstance(block_height, bool) or block_height < 1:
            logger.warning(f"[NetConsensus] {self.node_id} 丢弃 PRE-PREPARE：block_height 非法 ({block_height!r})")
            return
        legitimate = self.cw_pbft.get_primary(block_height)
        if primary_id != legitimate:
            logger.warning(f"[NetConsensus] {self.node_id} 丢弃 PRE-PREPARE：{primary_id} 并非高度 "
                           f"{block_height} 的合法主节点（应为 {legitimate}）")
            return

        # 如果处于上轮残留状态（COMMITTED），先重置再处理新轮
        from ..consensus.cw_pbft import ConsensusState as _CS
        # B3修复：临界区加锁，包裹 reset + receive_pre_prepare + _votes 修改
        with self._consensus_lock:
            if self.cw_pbft._state == _CS.COMMITTED:
                logger.info(f"[NetConsensus] {self.node_id} 收到新轮 PRE-PREPARE，重置上轮 COMMITTED 状态")
                self.cw_pbft.reset()

            prepare_vote = self.cw_pbft.receive_pre_prepare(block_hash, primary_id)
            self._round_height = block_height  # F13：本轮高度绑定，PREPARE/COMMIT 校验用

            # 关键：副本节点必须把自己的 PREPARE 票加入本地投票池！
            # 否则 _check_weight_threshold 统计时缺少自己的票，导致阈值永远不够
            self.cw_pbft._votes['prepare'][self.node_id] = prepare_vote

            # FT-FIX(2026-10-13)：_current_block_hash 已就绪，flush 早先乱序到达的 PREPARE
            # F13：乱序票携带各自 block_height，仅 flush 与本轮高度一致者
            to_broadcast = []
            for pending_vote, pending_height in self._pending_prepares:
                if pending_height != block_height:
                    logger.debug(f"[NetConsensus] {self.node_id} 丢弃乱序 PREPARE：高度 {pending_height} ≠ 本轮 {block_height}")
                    continue
                cv, cc = self._process_prepare_vote(pending_vote)
                if cv:
                    to_broadcast.append((cv, cc))
            self._pending_prepares.clear()

        # 锁外广播自己的 PREPARE（防止阻塞 event loop）
        await self._broadcast_vote(MessageType.CONSENSUS_PREPARE, prepare_vote, block_height=block_height)
        # 锁外广播 pending flush 产生的 COMMIT
        for cv, cc in to_broadcast:
            await self._broadcast_vote(MessageType.CONSENSUS_COMMIT, cv, block_height=block_height)
            if cc:
                logger.info(f"[NetConsensus] {self.node_id} confirmed consensus complete (pending flush)")

    async def _on_prepare(self, msg: Dict, from_node: str):
        """收到 PREPARE：验证签名后若达到 2/3 权重则广播 COMMIT"""
        self.msg_received += 1
        data = MessageProtocol.get_data(msg)
        voter_id = data.get("voter_id", from_node)

        # P1-7修复：验证投票签名，确认voter_id与签名公钥绑定
        if not await self._verify_vote_signature_auto(data, voter_id):
            logger.warning(f"[NetConsensus] {self.node_id} 丢弃 PREPARE：签名验证失败 from {voter_id}")
            return

        # F13：类型混淆封闭——签名体 phase 必须与本 handler 一致
        # （PREPARE 票签名被重放为 COMMIT 票在旧实现中可通过验签）。
        if data.get("phase") != "prepare":
            logger.warning(f"[NetConsensus] {self.node_id} 丢弃 PREPARE：phase 类型混淆 "
                           f"({data.get('phase')!r})")
            return
        block_height = data.get("block_height")
        if not isinstance(block_height, int) or isinstance(block_height, bool) or block_height < 1:
            logger.warning(f"[NetConsensus] {self.node_id} 丢弃 PREPARE：block_height 非法")
            return

        vote = ConsensusVote(
            voter_id=voter_id,
            block_hash=data.get("block_hash", ""),
            phase="prepare",
            weight=data.get("weight", 1.0),
        )
        logger.debug(f"[NetConsensus] {self.node_id} <- PREPARE from {from_node}")

        # B3修复：临界区加锁，保护 _state/_votes/_current_block_hash 并发访问
        with self._consensus_lock:
            # FT-FIX(2026-10-13)：PRE-PREPARE 尚未到达（乱序）→ 缓存而非丢弃，
            # 待 _on_preprepare 设置 _current_block_hash 后 flush。
            # F13：缓存携带票内 block_height，flush 时仅接受与本轮一致者。
            if self.cw_pbft._current_block_hash is None:
                self._pending_prepares.append((vote, block_height))
                logger.debug(f"[NetConsensus] {self.node_id} 缓存乱序 PREPARE from {voter_id} "
                             f"(pending={len(self._pending_prepares)})")
                return
            # F13：轮次绑定——与本节点当前轮高度不一致的票直接丢弃
            if block_height != getattr(self, '_round_height', None):
                logger.warning(f"[NetConsensus] {self.node_id} 丢弃 PREPARE：高度 {block_height} "
                               f"≠ 本轮 {getattr(self, '_round_height', None)}")
                return
            commit_vote, consensus_complete = self._process_prepare_vote(vote)
        # 锁外广播 + 日志
        if commit_vote:
            await self._broadcast_vote(MessageType.CONSENSUS_COMMIT, commit_vote, block_height=block_height)
            if consensus_complete:
                logger.info(f"[NetConsensus] {self.node_id} confirmed consensus complete (local)")

    async def _on_commit(self, msg: Dict, from_node: str):
        """收到 COMMIT：验证签名后若达到 2/3 权重则共识完成"""
        self.msg_received += 1
        data = MessageProtocol.get_data(msg)
        voter_id = data.get("voter_id", from_node)

        # P1-7修复：验证投票签名，确认voter_id与签名公钥绑定
        if not await self._verify_vote_signature_auto(data, voter_id):
            logger.warning(f"[NetConsensus] {self.node_id} 丢弃 COMMIT：签名验证失败 from {voter_id}")
            return

        # F13：类型混淆封闭（同 _on_prepare）
        if data.get("phase") != "commit":
            logger.warning(f"[NetConsensus] {self.node_id} 丢弃 COMMIT：phase 类型混淆 "
                           f"({data.get('phase')!r})")
            return
        block_height = data.get("block_height")
        if not isinstance(block_height, int) or isinstance(block_height, bool) or block_height < 1:
            logger.warning(f"[NetConsensus] {self.node_id} 丢弃 COMMIT：block_height 非法")
            return

        vote = ConsensusVote(
            voter_id=voter_id,
            block_hash=data.get("block_hash", ""),
            phase="commit",
            weight=data.get("weight", 1.0),
        )
        logger.debug(f"[NetConsensus] {self.node_id} <- COMMIT from {from_node}")

        # 严格校验：_current_block_hash 必须已由 start_consensus/receive_pre_prepare 设置
        # B3修复：临界区加锁，保护 _state/_votes/_current_block_hash 并发访问
        with self._consensus_lock:
            if self.cw_pbft._current_block_hash is None:
                logger.warning(f"[NetConsensus] {self.node_id} 丢弃 COMMIT：_current_block_hash 未设置")
                return
            if vote.block_hash != self.cw_pbft._current_block_hash:
                logger.warning(f"[NetConsensus] {self.node_id} 丢弃 COMMIT：hash 不匹配 "
                               f"({vote.block_hash[:8]} vs {self.cw_pbft._current_block_hash[:8]})")
                return
            # F13：轮次绑定
            if block_height != getattr(self, '_round_height', None):
                logger.warning(f"[NetConsensus] {self.node_id} 丢弃 COMMIT：高度 {block_height} "
                               f"≠ 本轮 {getattr(self, '_round_height', None)}")
                return

            # F13 封闭：COMMIT 票只统计"本节点自己已达成 prepared（进入 COMMIT 状态）"
            # 的轮次。旧实现直接把状态代推为 COMMIT——未 prepared 的节点也能靠他人
            # COMMIT 票凑齐阈值，三阶段退化为两阶段。
            from ..consensus.cw_pbft import ConsensusState as _CS
            if self.cw_pbft._state not in (_CS.COMMIT, _CS.COMMITTED):
                logger.warning(f"[NetConsensus] {self.node_id} 丢弃 COMMIT：本节点未达成 "
                               f"prepared（state={self.cw_pbft._state}），协议违例")
                return

            self.cw_pbft.receive_vote(vote)

            consensus_done = self.cw_pbft.is_consensus_reached()
            if consensus_done:
                self._consensus_result = True
                self._consensus_done.set()
        # 锁外日志
        if consensus_done:
            logger.info(f"[NetConsensus] {self.node_id} confirmed consensus complete")

    # -------------------------------------------------------------------------
    # 内部广播
    # -------------------------------------------------------------------------

    async def _broadcast_vote(self, msg_type: MessageType, vote: ConsensusVote,
                              block_height: Optional[int] = None):
        """
        将投票封装后广播给所有节点

        P1-7修复：发送投票前用proposer/voter的私钥对投票数据签名
        签名覆盖字段：voter_id + block_hash + phase + weight + timestamp
        F13（2026-11-02 赛后）：签名体追加 block_height——投票与具体轮次（高度）
        绑定，跨轮重放/换轮拼票被签名验证直接排除。
        """
        data = {
            "voter_id": vote.voter_id,
            "block_hash": vote.block_hash,
            "phase": vote.phase,
            "weight": vote.weight,
            "timestamp": vote.timestamp,
        }
        if block_height is not None:
            data["block_height"] = int(block_height)

        # P1-7修复：ECDSA签名投票数据
        signature_hex = None
        if self.key_manager is not None:
            priv_key = self.key_manager.get_private_key(vote.voter_id)
            if priv_key is not None:
                from ..crypto.ecdsa_utils import ECDSAUtils
                message_bytes = json.dumps(data, sort_keys=True).encode('utf-8')
                message_hash = hashlib.sha256(message_bytes).digest()
                sig = ECDSAUtils.sign(priv_key, message_hash)
                signature_hex = sig.hex()
                data["signature_hex"] = signature_hex  # 将签名附带在data中供接收方验证

        await self.p2p.broadcast(msg_type, data, signature=signature_hex)
        self.msg_sent += 1

    def _verify_vote_signature(self, data: Dict, voter_id: str) -> bool:
        """
        P1-7修复：验证投票消息的ECDSA签名

        验证流程：
        1. 从data中提取signature_hex
        2. 重新构造签名消息体（排除signature_hex自身）
        3. 用voter_id对应的公钥验签，确认voter_id与签名公钥绑定

        BUG2 修复：无 key_manager 时默认 fail-closed（拒绝投票），杜绝认证绕过后门。
        仅当显式开启 _allow_insecure_vote 且 key_manager 为 None 时，
        才允许无签名/长度兜底（仅用于纯连通性测试，非生产安全）。
        """
        signature_hex = data.get("signature_hex")
        if signature_hex is None:
            if self.key_manager is not None:
                logger.warning(f"[NetConsensus] 投票无签名: voter={voter_id}")
                return False
            # 无key_manager：默认 fail-closed（生产必须配置 key_manager）
            if self._allow_insecure_vote:
                logger.debug(f"[NetConsensus] 非生产安全模式(insecure)：放行无签名投票 voter={voter_id}")
                return True
            logger.warning(
                f"[NetConsensus] 投票签名验证失败(默认fail-closed): key_manager未配置且未开启"
                f"insecure模式，拒绝无签名投票 voter={voter_id}"
            )
            return False

        try:
            # 构造签名消息体（排除signature_hex自身）
            verify_data = {
                "voter_id": data.get("voter_id", ""),
                "block_hash": data.get("block_hash", ""),
                "phase": data.get("phase", ""),
                "weight": data.get("weight", 1.0),
                "timestamp": data.get("timestamp", 0),
                # F13：轮次高度进签名体验证体（与 _broadcast_vote 的签名体对称；
                # 旧报文缺该键时两侧同为 None，验签语义不变）
                "block_height": data.get("block_height"),
            }
            message_bytes = json.dumps(verify_data, sort_keys=True).encode('utf-8')
            message_hash = hashlib.sha256(message_bytes).digest()
            signature_bytes = bytes.fromhex(signature_hex)

            if self.key_manager is not None:
                pub_key = self.key_manager.get_public_key(voter_id)
                if pub_key is None:
                    logger.warning(f"[NetConsensus] 无法获取voter={voter_id}的公钥")
                    return False
                from ..crypto.ecdsa_utils import ECDSAUtils
                verified = ECDSAUtils.verify(pub_key, message_hash, signature_bytes)
                if not verified:
                    logger.warning(
                        f"[NetConsensus] 签名验证失败: voter={voter_id}，"
                        f"voter_id与签名公钥不绑定"
                    )
                return verified
            else:
                # 无key_manager：默认 fail-closed
                if self._allow_insecure_vote:
                    # 纵深防御（A 方案）：除长度≥64 外，要求签名为合法 DER 结构，
                    # 挡住纯垃圾字节（不绑定身份，仅防意外）；仍不真验签。
                    try:
                        from ..crypto.ecdsa_utils import ECDSAUtils
                        ECDSAUtils.extract_rs(signature_bytes)
                        return len(signature_bytes) >= 64
                    except Exception:
                        return False
                logger.warning(
                    f"[NetConsensus] 投票签名验证失败(默认fail-closed): key_manager未配置且未开启"
                    f"insecure模式，拒绝投票 voter={voter_id}"
                )
                return False
        except Exception as e:
            logger.warning(f"[NetConsensus] 签名验证异常: voter={voter_id}, {e}")
            return False

    async def _verify_vote_signature_async(self, data: Dict, voter_id: str) -> bool:
        """
        异步版投票签名验证（opt-in，仅当 use_async_verify=True 时由三处共识处理器调用）。

        与原同步 _verify_vote_signature 逻辑逐字对应，唯二差异：
        1. 本方法为 async def，调用方需 await；
        2. 公钥验签改用 ``await ECDSAUtils.verify_cached_async(...)``，把 CPU 密集的
           ECDSA 验签 offload 到 worker 线程，解除共识热路径对 event loop 的阻塞。
        默认关闭，故不改变任何现有同步行为；本方法本身零风险。
        """
        signature_hex = data.get("signature_hex")
        if signature_hex is None:
            if self.key_manager is not None:
                logger.warning(f"[NetConsensus] 投票无签名: voter={voter_id}")
                return False
            if self._allow_insecure_vote:
                logger.debug(f"[NetConsensus] 非生产安全模式(insecure)：放行无签名投票 voter={voter_id}")
                return True
            logger.warning(
                f"[NetConsensus] 投票签名验证失败(默认fail-closed): key_manager未配置且未开启"
                f"insecure模式，拒绝无签名投票 voter={voter_id}"
            )
            return False

        try:
            verify_data = {
                "voter_id": data.get("voter_id", ""),
                "block_hash": data.get("block_hash", ""),
                "phase": data.get("phase", ""),
                "weight": data.get("weight", 1.0),
                "timestamp": data.get("timestamp", 0),
                # F13：轮次高度进签名体验证体（与 _broadcast_vote 的签名体对称；
                # 旧报文缺该键时两侧同为 None，验签语义不变）
                "block_height": data.get("block_height"),
            }
            message_bytes = json.dumps(verify_data, sort_keys=True).encode('utf-8')
            message_hash = hashlib.sha256(message_bytes).digest()
            signature_bytes = bytes.fromhex(signature_hex)

            if self.key_manager is not None:
                pub_key = self.key_manager.get_public_key(voter_id)
                if pub_key is None:
                    logger.warning(f"[NetConsensus] 无法获取voter={voter_id}的公钥")
                    return False
                from ..crypto.ecdsa_utils import ECDSAUtils
                # 异步 offload：把 ECDSA 验签移到 worker 线程，避免阻塞 event loop
                verified = await ECDSAUtils.verify_cached_async(pub_key, message_hash, signature_bytes)
                if not verified:
                    logger.warning(
                        f"[NetConsensus] 签名验证失败: voter={voter_id}，"
                        f"voter_id与签名公钥不绑定"
                    )
                return verified
            else:
                if self._allow_insecure_vote:
                    # 纵深防御（A 方案）：除长度≥64 外，要求签名为合法 DER 结构，
                    # 挡住纯垃圾字节（不绑定身份，仅防意外）；仍不真验签。
                    try:
                        from ..crypto.ecdsa_utils import ECDSAUtils
                        ECDSAUtils.extract_rs(signature_bytes)
                        return len(signature_bytes) >= 64
                    except Exception:
                        return False
                logger.warning(
                    f"[NetConsensus] 投票签名验证失败(默认fail-closed): key_manager未配置且未开启"
                    f"insecure模式，拒绝投票 voter={voter_id}"
                )
                return False
        except Exception as e:
            logger.warning(f"[NetConsensus] 签名验证异常: voter={voter_id}, {e}")
            return False

    async def _verify_vote_signature_auto(self, data: Dict, voter_id: str) -> bool:
        """
        共识验签统一入口（opt-in 分支）：
        - use_batch_async_verify=True：走 _verify_vote_signature_batch（批量异步 offload，失败安全）；
        - use_async_verify=True：走 _verify_vote_signature_async（逐票异步 offload）；
        - 两者均默认 False：走原同步 _verify_vote_signature，行为与历史逐字一致。
        三处共识处理器统一通过本方法 await，所有开关关闭时零行为改动。
        """
        if self._use_batch_async_verify:
            return await self._verify_vote_signature_batch(data, voter_id)
        if self._use_async_verify:
            return await self._verify_vote_signature_async(data, voter_id)
        return self._verify_vote_signature(data, voter_id)

    # -------------------------------------------------------------------------
    # 共识投票批量异步验签 offload（opt-in，默认关闭；needs-design 热路径改造）
    # -------------------------------------------------------------------------

    def _verify_vote_signature_quick_decision(self, data: Dict, voter_id: str):
        """批量路径下『无需真验签即可定论』分支，返回 bool 或 None（None=需走真验签）。

        与 _verify_vote_signature 的无 crypto 分支逐字对应：
        - 无 signature_hex 且 key_manager 存在 -> False；
        - 无 signature_hex 且 key_manager 缺失 -> insecure 放行/拒绝；
        - key_manager 缺失 -> insecure 长度兜底/拒绝；
        - 公钥缺失 -> False。
        """
        sig_hex = data.get("signature_hex")
        if sig_hex is None:
            if self.key_manager is not None:
                return False
            return True if self._allow_insecure_vote else False
        if self.key_manager is None:
            if self._allow_insecure_vote:
                try:
                    from ..crypto.ecdsa_utils import ECDSAUtils
                    raw = bytes.fromhex(sig_hex)
                    ECDSAUtils.extract_rs(raw)
                    return len(raw) >= 64
                except Exception:
                    return False
            return False
        pub_key = self.key_manager.get_public_key(voter_id)
        if pub_key is None:
            return False
        return None  # 需走真验签

    async def _verify_vote_signature_batch(self, data: Dict, voter_id: str) -> bool:
        """批量异步验签路径（opt-in，仅 use_batch_async_verify=True 时由 _verify_vote_signature_auto 调用）。

        按 (block_height, phase) 缓冲到达的投票；缓冲达 batch_verify_threshold 或
        batch_verify_flush_timeout 超时后，一次 verify_batch_async 批量 offload。
        每张票独立拿到自己的布尔结果后才放行对应处理器——顺序保真、失败票统一丢弃。
        失败安全：批量验签抛异常时整批回退逐票同步，绝不漏检伪造票。
        """
        loop = asyncio.get_running_loop()
        key = (data.get("block_height"), data.get("phase"))
        fut = loop.create_future()
        buf = self._verify_batches.setdefault(key, [])
        buf.append((data, voter_id, fut))
        if len(buf) >= self._batch_threshold:
            await self._flush_verify_batch(key)
        elif key not in self._verify_batch_timers:
            self._verify_batch_timers[key] = loop.call_later(
                self._batch_flush_timeout,
                lambda k=key: asyncio.ensure_future(self._flush_verify_batch(k)),
            )
        return await fut

    async def _flush_verify_batch(self, key):
        """flush 一个 (block_height, phase) 缓冲：批量验签并逐票 set_result。

        失败安全：verify_batch_async 抛异常时，整批回退为逐票同步 _verify_vote_signature，
        保证可用性且不弱化验证（绝不漏检伪造票）。
        """
        pending = self._verify_batches.pop(key, [])
        timer = self._verify_batch_timers.pop(key, None)
        if timer is not None:
            timer.cancel()
        if not pending:
            return
        try:
            from ..crypto.ecdsa_utils import ECDSAUtils

            entries = []
            entry_map = []  # 与 pending 索引对齐（仅收录需真验签的票）
            for idx, (data, voter_id, fut) in enumerate(pending):
                if fut.done():
                    continue
                quick = self._verify_vote_signature_quick_decision(data, voter_id)
                if quick is not None:
                    fut.set_result(quick)
                    continue
                # 需真验签：构造与同步 _verify_vote_signature 对称的验签材料
                try:
                    verify_data = {
                        "voter_id": data.get("voter_id", ""),
                        "block_hash": data.get("block_hash", ""),
                        "phase": data.get("phase", ""),
                        "weight": data.get("weight", 1.0),
                        "timestamp": data.get("timestamp", 0),
                        "block_height": data.get("block_height"),
                    }
                    message_bytes = json.dumps(verify_data, sort_keys=True).encode('utf-8')
                    message_hash = hashlib.sha256(message_bytes).digest()
                    signature_bytes = bytes.fromhex(data["signature_hex"])
                    pub_key = self.key_manager.get_public_key(voter_id)
                    entries.append((pub_key, message_hash, signature_bytes))
                    entry_map.append(idx)
                except Exception:
                    # 材料构造失败（如坏 hex）：直接判 False（与同步外层 except 同口径）
                    fut.set_result(False)
            if entries:
                results = await ECDSAUtils.verify_batch_async(entries)
                for r_i, p_idx in enumerate(entry_map):
                    _, _, fut = pending[p_idx]
                    fut.set_result(results[r_i])
        except Exception:
            # 整批回退逐票同步（绝不漏检）
            for (data, voter_id, fut) in pending:
                if not fut.done():
                    fut.set_result(self._verify_vote_signature(data, voter_id))

    # -------------------------------------------------------------------------
    # 权重更新（由外部激励模块调用）
    # -------------------------------------------------------------------------

    def update_weight(self, node_id: str, weight: float):
        self.cw_pbft.update_weight(node_id, weight)

    def get_weights(self) -> Dict[str, float]:
        return self.cw_pbft.get_weights()

    def get_stats(self) -> Dict:
        return {
            "node_id": self.node_id,
            "port": self.port,
            "msg_sent": self.msg_sent,
            "msg_received": self.msg_received,
            "consensus_rounds": self.consensus_rounds,
            "network": self.p2p.get_network_stats(),
            "weights": self.get_weights(),
        }


# =============================================================================
# 多节点网络管理器（一键启动整个 P2P 共识网络）
# =============================================================================

class P2PConsensusNetwork:
    """
    多节点 P2P 共识网络管理器
    一键启动 N 个 ConsensusNode，自动完成 全连接拓扑 建立

    使用方式：
        net = P2PConsensusNetwork(n_nodes=3, base_port=7001)
        net.start()
        success = net.run_consensus(block_hash)
        stats = net.get_stats()
        net.stop()
    """

    BASE_HOST = "127.0.0.1"

    def __init__(self, n_nodes: int = 3, base_port: int = 7001, key_manager=None,
                 consensus_mode: str = None,
                 allow_insecure_vote: bool = False,  # BUG2: 透传
                 allow_insecure_register: bool = False,  # BUG1: 透传
                 enable_tls: bool = True,  # BUG4: 默认开启
                 tls_dir: str = "keys/tls",  # BUG4: 透传
                 node_addrs: Optional[Dict[str, tuple]] = None,  # D3 跨主机：node_id -> (host, port)
                 local_node_ids: Optional[List[str]] = None,  # D3 跨主机：本进程启动的节点子集
                 use_async_verify: bool = False,  # 共识验签异步 offload 开关（透传，默认关闭）
                 use_batch_async_verify: bool = False):  # 共识投票批量异步验签 offload 开关（透传，默认关闭）
        self.n_nodes = n_nodes
        self.base_port = base_port
        self.node_ids = [f"agent_{i}" for i in range(n_nodes)]
        self.nodes: Dict[str, NetworkConsensusNode] = {}
        self._started = False
        self.key_manager = key_manager  # P1-7修复：注入KeyManager
        self.consensus_mode = consensus_mode  # cw_pbft / standard_pbft / fast
        # BUG1/BUG2/BUG4: 透传安全开关
        self._allow_insecure_vote = allow_insecure_vote
        self._allow_insecure_register = allow_insecure_register
        self._enable_tls = enable_tls
        self._tls_dir = tls_dir
        # D3 跨主机支持：node_addrs 提供全网节点真实地址；local_node_ids 限定本进程负责的节点。
        # 默认均为 None 时行为与单机回环模式完全一致（BASE_HOST + base_port 递增）。
        self._node_addrs = dict(node_addrs) if node_addrs else {}
        self._local_node_ids = list(local_node_ids) if local_node_ids else list(self.node_ids)
        # 共识验签异步 offload 开关（透传，默认关闭）
        self._use_async_verify = use_async_verify
        # 共识投票批量异步验签 offload 开关（透传，默认关闭）
        self._use_batch_async_verify = use_batch_async_verify

        # 统计
        self.total_consensus_rounds = 0
        self.total_msg_sent = 0
        self.total_msg_received = 0
        self.network_msg_log: List[Dict] = []   # 消息事件日志（供 Dashboard 展示）

    def _addr_of(self, node_id: str):
        """返回节点的 (host, port)。跨主机模式下取 node_addrs，否则走单机回环递增。"""
        if node_id in self._node_addrs:
            host, port = self._node_addrs[node_id]
            return host, int(port)
        i = self.node_ids.index(node_id)
        return self.BASE_HOST, self.base_port + i

    def start(self):
        """启动所有节点并建立全连接拓扑（D3 支持跨主机：只启动本进程负责的节点）"""
        if self._started:
            return

        # 1. 创建并启动本地节点（单机模式下 = 全部节点）
        for node_id in self._local_node_ids:
            host, port = self._addr_of(node_id)
            node = NetworkConsensusNode(
                node_id=node_id,
                host=host,
                port=port,
                all_node_ids=self.node_ids,
                key_manager=self.key_manager,  # P1-7修复：传递key_manager
                consensus_mode=self.consensus_mode,  # 共识模式透传
                allow_insecure_vote=self._allow_insecure_vote,  # BUG2 透传
                allow_insecure_register=self._allow_insecure_register,  # BUG1 透传
                enable_tls=self._enable_tls,  # BUG4 透传
                tls_dir=self._tls_dir,  # BUG4 透传
                use_async_verify=self._use_async_verify,  # 共识验签异步 offload 开关（透传）
                use_batch_async_verify=self._use_batch_async_verify,  # 共识投票批量异步验签 offload 开关（透传）
            )
            node.start()
            self.nodes[node_id] = node

        time.sleep(0.3)   # 等待所有节点 TCP 服务就绪

        # 2. 建立全连接拓扑：编号小的连编号大的（每对只有1条TCP连接）
        #    TCP 本身是双向的——双方都能通过同一条连接读写
        #    避免双向连接导致 _connections 被覆盖、_read_loop 遗弃等问题
        #    D3 跨主机：src 只遍历本进程节点，dst 遍历全网编号更大的节点，
        #    对端地址取自全网地址表（跨物理主机时即对端真实 IP:port）。
        connection_failures = []
        for src_id in self._local_node_ids:
            src_idx = self.node_ids.index(src_id)
            for j in range(src_idx + 1, self.n_nodes):
                dst_id = self.node_ids[j]
                dst_host, dst_port = self._addr_of(dst_id)
                try:
                    connected = self.nodes[src_id].connect_to(
                        dst_id, dst_host, dst_port
                    )
                    if connected:
                        logger.info(f"[P2PNetwork] {src_id} ──→ {dst_id}@{dst_host}:{dst_port}")
                    else:
                        connection_failures.append(f"{src_id}→{dst_id}")
                        logger.warning(
                            f"[P2PNetwork] 连接失败 {src_id}→{dst_id}: connect_to 返回 False"
                        )
                except Exception as e:
                    connection_failures.append(f"{src_id}→{dst_id}")
                    logger.warning(f"[P2PNetwork] 连接失败 {src_id}→{dst_id}: {e}")

        if connection_failures:
            for node in self.nodes.values():
                try:
                    node.stop()
                except Exception as e:
                    logger.warning(f"[P2PNetwork] 启动失败后停止节点 {node.node_id} 异常: {e}")
            self._started = False
            raise RuntimeError(
                "P2P 全连接拓扑建立失败: " + ", ".join(connection_failures)
            )

        time.sleep(0.2)   # 等待握手完成
        self._started = True
        if len(self._local_node_ids) < self.n_nodes:
            logger.info(
                f"[P2PNetwork] ✅ 本进程节点 {len(self.nodes)}/{self.n_nodes} 启动，"
                f"全连接拓扑建立完成（跨主机分布式模式）"
            )
        else:
            logger.info(f"[P2PNetwork] ✅ {self.n_nodes} 节点网络启动，全连接拓扑建立完成")

    def run_consensus(self, block_hash: str, block_height: int = 1) -> bool:
        """
        运行一轮真实 P2P CW-PBFT 共识
        :param block_hash: 待确认的区块哈希
        :param block_height: 本轮区块高度（F13：主节点按 get_primary(block_height)
            轮换确定，随 PRE-PREPARE 进签名体，副本校验主节点合法性）
        :return: 是否达成共识
        """
        if not self._started:
            self.start()

        # 每轮开始前重置所有节点的 CW-PBFT 状态
        # 等待上一轮异步消息处理完毕（增加等待时间，确保 TCP 缓冲区清空）
        time.sleep(0.3)
        for node in self.nodes.values():
            node.cw_pbft.reset()
            node._consensus_done.clear()
            node._consensus_result = None
            node._round_height = None  # F13：轮次绑定随轮重置
            # 安全清空 msg_id 去重缓存（通过 event loop，避免线程冲突）
            node.clear_msg_cache()

        # 再等待一小段时间，让 reset 后的异步清理完成
        time.sleep(0.1)

        # F13：主节点不再由调用方任意指定（primary_idx），按高度轮换推导——
        # 调用方指定主节点 = 任何成员都能发起任意轮，主节点合法性校验形同虚设。
        any_node = next(iter(self.nodes.values()))
        primary_id = any_node.cw_pbft.get_primary(int(block_height))
        if primary_id not in self.nodes:
            # D3 跨主机：主节点不在本进程时无法由本进程发起共识。
            # 分布式启动脚本保证只有主节点所在进程调用 run_consensus，此处仅作防御。
            raise RuntimeError(
                f"高度 {block_height} 的合法主节点 {primary_id} 不在本进程节点 "
                f"{list(self.nodes.keys())} 中，无法由本进程发起共识（跨主机模式下请由主节点所在主机发起）"
            )
        primary_node = self.nodes[primary_id]

        t0 = time.time()
        result = primary_node.propose_consensus(block_hash, block_height=int(block_height), timeout=3.0)
        # F13：完成判定不再只看主节点布尔值——本进程内全部副本必须都到达
        # COMMITTED（跨主机模式下远端副本不可本进程观测，边界照旧登记）。
        # 副本经异步消息达到 COMMITTED 略晚于主节点，给 2s 宽限轮询。
        from ..consensus.cw_pbft import ConsensusState as _CS
        deadline = time.time() + 2.0
        local_committed = False
        while time.time() < deadline:
            if all(n.cw_pbft._state == _CS.COMMITTED for n in self.nodes.values()):
                local_committed = True
                break
            time.sleep(0.05)
        result = bool(result) and local_committed
        elapsed_ms = int((time.time() - t0) * 1000)

        # 日志记录
        entry = {
            "round": self.total_consensus_rounds,
            "block_hash": block_hash[:16],
            "primary": primary_id,
            "success": result,
            "elapsed_ms": elapsed_ms,
            "timestamp": int(time.time() * 1000),
        }
        self.network_msg_log.append(entry)

        self.total_consensus_rounds += 1
        if result:
            logger.info(
                f"[P2PNetwork] 第{self.total_consensus_rounds}轮共识 ✅ "
                f"主节点={primary_id} 用时={elapsed_ms}ms"
            )
        else:
            logger.warning(
                f"[P2PNetwork] 第{self.total_consensus_rounds}轮共识 ❌ 超时"
            )
        return result

    def update_weights(self, weight_dict: Dict[str, float]):
        """更新所有节点的贡献权重"""
        for node_id, weight in weight_dict.items():
            if node_id in self.nodes:
                for target_node in self.nodes.values():
                    target_node.update_weight(node_id, weight)

    def get_weights(self) -> Dict[str, float]:
        """获取当前投票权重（从任意节点读取）"""
        if not self.nodes:
            return {}
        first = next(iter(self.nodes.values()))
        return first.get_weights()

    def stop(self):
        """停止所有节点"""
        for node in self.nodes.values():
            try:
                node.stop()
            except Exception as e:
                logger.warning(f"停止节点 {node.node_id} 时出错: {e}")
        self._started = False
        logger.info("[P2PNetwork] 所有节点已停止")

    def get_stats(self) -> Dict:
        """获取网络汇总统计"""
        total_sent = sum(n.msg_sent for n in self.nodes.values())
        total_recv = sum(n.msg_received for n in self.nodes.values())
        node_stats = {nid: node.get_stats() for nid, node in self.nodes.items()}

        return {
            "n_nodes": self.n_nodes,
            "total_consensus_rounds": self.total_consensus_rounds,
            "total_msg_sent": total_sent,
            "total_msg_received": total_recv,
            "weights": self.get_weights(),
            "nodes": node_stats,
            "recent_log": self.network_msg_log[-20:],   # 最近20条日志
        }

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

"""
区块链主体
维护完整的链式账本，提供区块查询、新区块追加、链式验证功能
"""
import json
import logging
import threading
from typing import List, Optional, Dict

from .block import Block, Transaction
from ..crypto.ecdsa_utils import ECDSAUtils

logger = logging.getLogger(__name__)


class Blockchain:
    """
    轻量级联盟链账本
    - 链式哈希存储（不可篡改）
    - 内存+持久化双重存储
    - 线程安全（读写锁）
    - 单链顺序追加；冲突区块 fail-closed 拒绝并记录（不重组、无最长链选择逻辑，
      仅适配 BFT 即时最终性场景，概率最终性链型的重组路径不在本实现范围内）
    - 交易池容量上限保护（P2-2）
    """

    MAX_TX_POOL_SIZE = 10000  # 交易池容量上限（防止内存溢出）

    # P0-3: 增加 identity_contract 参数，用于验证交易签名时获取公钥
    def __init__(self, persist_path: Optional[str] = None, identity_contract=None,
                 allow_unsigned_stub: bool = False):
        self._chain: List[Block] = [Block.create_genesis()]
        self._lock = threading.RLock()  # 可重入锁（get_stats内部调用self.height也需获取锁）
        self._persist_path = persist_path
        # P0-3: 身份合约引用，用于交易签名验证时获取智能体公钥
        self._identity_contract = identity_contract
        # R1 收紧（2026-10-18，用户拍板 1A）：identity_contract 未配置时缺签名交易
        # 默认拒绝（fail-closed）；stub/测试路径需显式传 allow_unsigned_stub=True
        # 才放行（原行为为 debug 级警告后放行，存在 stub 模式无防线攻击面）
        self._allow_unsigned_stub = allow_unsigned_stub
        # 交易池：待打包的交易
        self._tx_pool: List[Transaction] = []
        self._tx_pool_lock = threading.Lock()
        self._pool_full_warned = False  # 交易池满仅告警一次，避免训练日志刷屏

        if persist_path:
            self._try_load()

    # -------------------------------------------------------------------------
    # 核心接口
    # -------------------------------------------------------------------------

    @property
    def height(self) -> int:
        """当前区块链高度"""
        with self._lock:
            return len(self._chain) - 1

    @property
    def latest_block(self) -> Block:
        """最新区块"""
        with self._lock:
            return self._chain[-1]

    def get_block(self, height: int) -> Optional[Block]:
        """按高度查询区块"""
        with self._lock:
            if 0 <= height < len(self._chain):
                return self._chain[height]
        return None

    def get_blocks_from(self, start_height: int) -> List[Block]:
        """获取从指定高度开始的所有区块（用于同步）"""
        with self._lock:
            return list(self._chain[start_height:])

    # -------------------------------------------------------------------------
    # 交易池管理
    # -------------------------------------------------------------------------

    def add_transaction(self, tx: Transaction) -> bool:
        """将交易加入交易池"""
        with self._tx_pool_lock:
            # 容量上限检查（P2-2）
            if len(self._tx_pool) >= self.MAX_TX_POOL_SIZE:
                if not self._pool_full_warned:
                    logger.warning(
                        f"[Blockchain] 交易池已满({len(self._tx_pool)}/{self.MAX_TX_POOL_SIZE})，"
                        f"后续交易将被拒绝（审计账本容量上限，不影响激励结算）"
                    )
                    self._pool_full_warned = True
                return False
            # 去重检查
            existing_ids = {t.tx_id for t in self._tx_pool}
            if tx.tx_id in existing_ids:
                logger.debug(f"[Blockchain] 交易 {tx.tx_id[:8]} 已在交易池中")
                return False
            self._tx_pool.append(tx)
            logger.debug(f"[Blockchain] 交易 {tx.tx_id[:8]} 加入交易池，当前池大小: {len(self._tx_pool)}")
            return True

    def get_pending_transactions(self, max_count: int = 100) -> List[Transaction]:
        """获取待打包交易"""
        with self._tx_pool_lock:
            return list(self._tx_pool[:max_count])

    def get_tx_pool_size(self) -> int:
        with self._tx_pool_lock:
            return len(self._tx_pool)

    # -------------------------------------------------------------------------
    # 区块追加
    # -------------------------------------------------------------------------

    def append_block(self, block: Block) -> bool:
        """
        追加新区块到链末尾
        :return: True=追加成功，False=区块无效

        P2-10 锁获取顺序规则：必须先 _lock 后 _tx_pool_lock，不可逆转。
        当前实现：_lock(RLock) → _tx_pool_lock(Lock)，安全。
        反序（先 _tx_pool_lock 后 _lock）可能导致死锁：
        线程A: _lock → _tx_pool_lock（当前路径，安全）
        线程B: _tx_pool_lock → _lock（如果存在此路径，则与线程A交叉死锁）
        add_transaction 只获取 _tx_pool_lock 不获取 _lock，所以目前无线程B路径。
        """
        with self._lock:
            if not self._validate_new_block(block):
                return False

            self._chain.append(block)

            # 从交易池中移除已上链交易
            tx_ids = {tx.tx_id for tx in block.transactions}
            with self._tx_pool_lock:
                self._tx_pool = [t for t in self._tx_pool if t.tx_id not in tx_ids]

            logger.info(
                f"[Blockchain] 区块 #{block.block_height} 追加成功 "
                f"| 交易数={len(block.transactions)} "
                f"| hash={block.block_hash[:16]}..."
            )

            if self._persist_path:
                self._save_latest(block)

            return True

    # -------------------------------------------------------------------------
    # 区块验证
    # -------------------------------------------------------------------------

    def _validate_new_block(self, block: Block) -> bool:
        """验证新区块的合法性（含交易签名验证 — P0-3 安全加固）"""
        latest = self._chain[-1]

        if not block.is_valid_chain_link(latest):
            logger.warning(
                f"[Blockchain] 区块 #{block.block_height} 链式验证失败: "
                f"prev_hash={block.previous_hash[:16]}... "
                f"expected={latest.block_hash[:16]}..."
            )
            return False

        # 验证哈希计算
        expected_hash = block._compute_hash()
        if block.block_hash != expected_hash:
            logger.warning(f"[Blockchain] 区块 #{block.block_height} 哈希不匹配")
            return False

        # 2026-11-02 审查修复：区块级完整性校验（**出块者签名 + state_root 可重算**）。
        # 此前签名"只签不验、且不入哈希"，任何人可任意替换 signature_hex/state_root
        # 而不被发现——区块头缺少任何可验证的出块者绑定。
        # 门控：仅在「已配置身份合约的真实链」上启用（与下方交易级校验同门控）；
        # 有意产出无签名/占位 state_root 的合成路径（基准/演示）须显式
        # allow_unsigned_stub=True 声明。测试用 Blockchain()（未配 identity_contract）
        # 亦不受影响。
        if self._identity_contract is not None and not self._allow_unsigned_stub:
            # (1) 出块者签名必须存在且可由其注册公钥验证
            if not block.signature_hex:
                logger.warning(
                    f"[Blockchain] 区块 #{block.block_height} 缺少出块者签名，拒绝上链"
                )
                return False
            proposer_pub_hex = self._identity_contract.get_public_key(block.proposer)
            if proposer_pub_hex is None:
                logger.warning(
                    f"[Blockchain] 区块 #{block.block_height} 出块者 "
                    f"{block.proposer} 公钥未注册，拒绝上链"
                )
                return False
            try:
                proposer_pub = ECDSAUtils.public_key_from_hex(proposer_pub_hex)
                if not ECDSAUtils.verify(
                    proposer_pub,
                    bytes.fromhex(block.block_hash),
                    bytes.fromhex(block.signature_hex),
                ):
                    logger.warning(
                        f"[Blockchain] 区块 #{block.block_height} 出块者签名验证失败 "
                        f"(proposer={block.proposer})"
                    )
                    return False
            except Exception as e:
                logger.warning(
                    f"[Blockchain] 区块 #{block.block_height} 出块者签名验证异常: {e}"
                )
                return False

            # (2) state_root 必须等于对交易 tx_id 重算的 Merkle 根
            expected_state_root = block.compute_state_root()
            if block.state_root != expected_state_root:
                logger.warning(
                    f"[Blockchain] 区块 #{block.block_height} state_root 不匹配 "
                    f"(声明={str(block.state_root)[:16]}... "
                    f"重算={expected_state_root[:16]}...)"
                )
                return False

        # P0-3: 验证区块内每笔交易的签名完整性
        # 当 identity_contract 已配置时，严格拒绝 verified=False 或空签名的交易
        # R1 收紧（2026-10-18 拍板 1A）：identity_contract 未配置时缺签名/verified=False
        # 默认拒绝（fail-closed）；仅显式 allow_unsigned_stub=True 的测试/stub 路径放行
        for tx in block.transactions:
            # 空签名检查
            if not tx.signature_hex or tx.signature_hex == "":
                if self._identity_contract is not None:
                    logger.warning(
                        f"[Blockchain] 交易 {tx.tx_id[:8]} 缺少签名，拒绝上链 "
                        f"(agent={tx.agent_id})"
                    )
                    return False
                elif not self._allow_unsigned_stub:
                    logger.warning(
                        f"[Blockchain] 交易 {tx.tx_id[:8]} 缺少签名且 identity_contract 未配置，拒绝上链 "
                        f"(agent={tx.agent_id}；测试/stub 路径请显式传 allow_unsigned_stub=True)"
                    )
                    return False
                else:
                    logger.debug(
                        f"[Blockchain] 交易 {tx.tx_id[:8]} 缺少签名（stub 模式显式放行）"
                    )

            # verified 字段检查
            verified = tx.extra.get('verified', False)
            if not verified:
                if self._identity_contract is not None:
                    logger.warning(
                        f"[Blockchain] 交易 {tx.tx_id[:8]} verified=False，拒绝上链 "
                        f"(agent={tx.agent_id})"
                    )
                    return False
                elif not self._allow_unsigned_stub:
                    logger.warning(
                        f"[Blockchain] 交易 {tx.tx_id[:8]} verified=False 且 identity_contract 未配置，拒绝上链 "
                        f"(agent={tx.agent_id}；测试/stub 路径请显式传 allow_unsigned_stub=True)"
                    )
                    return False
                else:
                    logger.debug(
                        f"[Blockchain] 交易 {tx.tx_id[:8]} verified=False（stub 模式显式放行）"
                    )

            # F05（2026-11-02 赛后）：封禁身份准入——is_active=False（BANNED）的
            # 交易拒绝上链。此前 ECDSA 验签只证明"持有注册私钥"，封禁身份照样过。
            if self._identity_contract is not None and not self._identity_contract.is_active(tx.agent_id):
                logger.warning(
                    f"[Blockchain] 交易 {tx.tx_id[:8]} 发送方 {tx.agent_id} 已被封禁，拒绝上链"
                )
                return False

            # ECDSA 签名验证：使用 identity_contract 获取公钥
            if self._identity_contract is not None and tx.signature_hex:
                pub_key_hex = self._identity_contract.get_public_key(tx.agent_id)
                if pub_key_hex is not None:
                    try:
                        pub_key = ECDSAUtils.public_key_from_hex(pub_key_hex)
                        package = {
                            'agent_id': tx.agent_id,
                            'action': tx.action,
                            'timestamp': tx.timestamp,
                            'nonce': tx.nonce,
                            'message_hex': tx.extra.get('message_hex', ''),
                            'signature_hex': tx.signature_hex,
                            'r': tx.extra.get('r'),
                            's': tx.extra.get('s'),
                        }
                        if not ECDSAUtils.verify_action_package(package, pub_key):
                            logger.warning(
                                f"[Blockchain] 交易 {tx.tx_id[:8]} ECDSA签名验证失败 "
                                f"(agent={tx.agent_id})"
                            )
                            return False
                    except Exception as e:
                        logger.warning(
                            f"[Blockchain] 交易 {tx.tx_id[:8]} 签名验证异常: {e}"
                        )
                        return False
                else:
                    logger.warning(
                        f"[Blockchain] 交易 {tx.tx_id[:8]} 发送方 {tx.agent_id} "
                        f"公钥未注册，拒绝上链"
                    )
                    return False

        return True

    def _verify_block_integrity(self, block: Block) -> bool:
        """F09：区块内容级深度校验（出块者签名 + state_root 重算 + 逐交易 ECDSA 复验）。
        与 append 时 `_validate_new_block` 相同的 strict 门控（identity_contract +
        allow_unsigned_stub），供 `validate_chain(deep=True)` 全链复扫使用；不改写入路径。
        能捕获：历史区块 state_root/tx_id 被改、交易 action 明文被篡改而保留 tx_id、
        verified=False、封禁身份、出块者签名伪造——这些都是仅比对 block_hash 漏掉的。
        """
        if self._identity_contract is not None and not self._allow_unsigned_stub:
            if not block.signature_hex:
                logger.error(f"[Blockchain] 深验：区块 #{block.block_height} 缺出块者签名")
                return False
            proposer_pub_hex = self._identity_contract.get_public_key(block.proposer)
            if proposer_pub_hex is None:
                logger.error(f"[Blockchain] 深验：区块 #{block.block_height} 出块者公钥未注册")
                return False
            try:
                proposer_pub = ECDSAUtils.public_key_from_hex(proposer_pub_hex)
                if not ECDSAUtils.verify(proposer_pub, bytes.fromhex(block.block_hash),
                                         bytes.fromhex(block.signature_hex)):
                    logger.error(f"[Blockchain] 深验：区块 #{block.block_height} 出块者签名失败")
                    return False
            except Exception as e:
                logger.error(f"[Blockchain] 深验：区块 #{block.block_height} 出块者签名异常: {e}")
                return False
            if block.state_root != block.compute_state_root():
                logger.error(f"[Blockchain] 深验：区块 #{block.block_height} state_root 不等于交易 Merkle 根")
                return False

        for tx in block.transactions:
            if not tx.signature_hex:
                if self._identity_contract is not None or not self._allow_unsigned_stub:
                    logger.error(f"[Blockchain] 深验：交易 {tx.tx_id[:8]} 缺签名")
                    return False
            if not tx.extra.get('verified', False):
                if self._identity_contract is not None or not self._allow_unsigned_stub:
                    logger.error(f"[Blockchain] 深验：交易 {tx.tx_id[:8]} verified=False")
                    return False
            if self._identity_contract is not None:
                if not self._identity_contract.is_active(tx.agent_id):
                    logger.error(f"[Blockchain] 深验：交易 {tx.tx_id[:8]} 发送方 {tx.agent_id} 已被封禁")
                    return False
                if tx.signature_hex:
                    pub_key_hex = self._identity_contract.get_public_key(tx.agent_id)
                    if pub_key_hex is None:
                        logger.error(f"[Blockchain] 深验：交易 {tx.tx_id[:8]} 发送方公钥未注册")
                        return False
                    try:
                        pub_key = ECDSAUtils.public_key_from_hex(pub_key_hex)
                        package = {
                            'agent_id': tx.agent_id, 'action': tx.action,
                            'timestamp': tx.timestamp, 'nonce': tx.nonce,
                            'message_hex': tx.extra.get('message_hex', ''),
                            'signature_hex': tx.signature_hex,
                            'r': tx.extra.get('r'), 's': tx.extra.get('s'),
                        }
                        if not ECDSAUtils.verify_action_package(package, pub_key):
                            logger.error(f"[Blockchain] 深验：交易 {tx.tx_id[:8]} ECDSA 签名验证失败")
                            return False
                    except Exception as e:
                        logger.error(f"[Blockchain] 深验：交易 {tx.tx_id[:8]} 签名异常: {e}")
                        return False
        return True

    def validate_chain(self, deep: bool = False) -> bool:
        """验证整条链的完整性（从头到尾）。

        deep=False（默认）：仅校验链式链接 + 区块自哈希（保持既有语义，零回归）。
        deep=True（F09）：对每个非创世块额外跑 `_verify_block_integrity`——重算 state_root、
        复验逐交易 ECDSA 签名与 verified/封禁，捕获历史交易改明文保留 tx_id 等仅比对哈希漏掉的篡改。
        """
        with self._lock:
            for i in range(1, len(self._chain)):
                curr = self._chain[i]
                prev = self._chain[i - 1]
                if not curr.is_valid_chain_link(prev):
                    logger.error(f"[Blockchain] 链式验证失败于区块 #{i}")
                    return False
                expected_hash = curr._compute_hash()
                if curr.block_hash != expected_hash:
                    logger.error(f"[Blockchain] 区块 #{i} 哈希被篡改")
                    return False
                if deep and not self._verify_block_integrity(curr):
                    logger.error(f"[Blockchain] 深度验证失败于区块 #{i}")
                    return False
            return True

    # -------------------------------------------------------------------------
    # 交易查询
    # -------------------------------------------------------------------------

    def find_transaction(self, tx_id: str) -> Optional[Transaction]:
        """在全链中查找指定交易"""
        with self._lock:
            for block in reversed(self._chain):
                for tx in block.transactions:
                    if tx.tx_id == tx_id:
                        return tx
        return None

    def get_agent_transactions(self, agent_id: str, limit: int = 100) -> List[Transaction]:
        """获取指定智能体的历史交易"""
        result = []
        with self._lock:
            for block in reversed(self._chain):
                for tx in block.transactions:
                    if tx.agent_id == agent_id:
                        result.append(tx)
                        if len(result) >= limit:
                            return result
        return result

    # -------------------------------------------------------------------------
    # 持久化
    # -------------------------------------------------------------------------

    def _try_load(self):
        """尝试从文件加载历史区块链数据

        2026-11-02 审查修复（fail-closed）：此前直接 `self._chain = blocks`
        采信磁盘上的 block_hash，加载后从不调用 validate_chain()——任何被篡改/
        损坏的落盘链都会被原样载入并参与后续追加。现于加载后立即验链，
        不通过则拒绝采用并回退为全新创世链。
        """
        try:
            import os
            if os.path.exists(self._persist_path):
                with open(self._persist_path, 'r') as f:
                    data = json.load(f)
                blocks = [Block.from_dict(b) for b in data]
                if blocks:
                    self._chain = blocks
                    if self.validate_chain():
                        logger.info(f"[Blockchain] 从磁盘加载链，高度={self.height}")
                    else:
                        logger.error(
                            "[Blockchain] 落盘链未通过完整性校验，拒绝采用"
                            "（fail-closed），回退为全新创世链"
                        )
                        self._chain = [Block.create_genesis()]
        except Exception as e:
            logger.warning(f"[Blockchain] 加载持久化数据失败: {e}，使用全新链")

    def _save_latest(self, block: Block):
        """追加保存最新区块"""
        try:
            data = [b.to_dict() for b in self._chain]
            with open(self._persist_path, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[Blockchain] 持久化区块失败: {e}")

    # -------------------------------------------------------------------------
    # 统计信息
    # -------------------------------------------------------------------------

    def get_stats(self) -> Dict:
        """获取区块链统计信息"""
        with self._lock:
            total_txs = sum(len(b.transactions) for b in self._chain)
            return {
                'height': self.height,
                'total_blocks': len(self._chain),
                'total_transactions': total_txs,
                'latest_hash': self._chain[-1].block_hash[:16] + '...',
                'pending_transactions': self.get_tx_pool_size(),
            }

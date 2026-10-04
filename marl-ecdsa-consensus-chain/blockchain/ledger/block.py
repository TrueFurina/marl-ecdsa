"""
区块与交易数据结构
实现链式哈希存储，保证数据不可篡改
"""
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


def compute_merkle_root(tx_hashes: List[str]) -> str:
    """
    计算交易哈希列表的 Merkle 树根。

    对空列表返回空字符串，对单元素列表返回该元素本身，
    否则逐层两两哈希直到得到根。
    """
    if not tx_hashes:
        return ""
    if len(tx_hashes) == 1:
        return tx_hashes[0]

    nodes = [bytes.fromhex(h) for h in tx_hashes]
    while len(nodes) > 1:
        if len(nodes) % 2 == 1:
            nodes.append(nodes[-1])  # 复制最后一个节点使长度为偶数
        new_nodes = []
        for i in range(0, len(nodes), 2):
            combined = nodes[i] + nodes[i + 1]
            new_nodes.append(hashlib.sha256(combined).digest())
        nodes = new_nodes
    return nodes[0].hex()


@dataclass
class Transaction:
    """
    智能体行为交易
    每个MARL训练步骤的行为决策通过交易上链存证
    """
    tx_id: str                  # 交易唯一ID（消息哈希）
    agent_id: str               # 发送方智能体ID
    action: Any                 # 智能体行为数据
    action_hash: str            # 行为哈希（防篡改）
    timestamp: int              # 交易时间戳（毫秒）
    nonce: int                  # 防重放nonce
    signature_hex: str          # ECDSA签名（十六进制）
    tx_type: str = "action"     # 交易类型: action/register/score/penalty
    extra: Dict = field(default_factory=dict)  # 扩展字段

    def to_dict(self) -> Dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict) -> 'Transaction':
        return Transaction(**d)

    def compute_hash(self) -> str:
        """计算交易哈希（不含tx_id本身）"""
        data = {
            'agent_id': self.agent_id,
            'action_hash': self.action_hash,
            'timestamp': self.timestamp,
            'nonce': self.nonce,
            'tx_type': self.tx_type,
        }
        return hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()


@dataclass
class Block:
    """
    区块数据结构
    采用哈希链式结构，每个区块包含前一区块哈希
    任何历史篡改都会导致后续区块哈希失效
    """
    block_height: int               # 区块高度（递增唯一）
    previous_hash: str              # 前一区块哈希
    timestamp: int                  # 区块生成时间戳（毫秒）
    proposer: str                   # 出块节点ID
    transactions: List[Transaction] # 本轮所有智能体行为交易
    state_root: str                 # 世界状态默克尔根
    signature_hex: str = ""         # 出块节点ECDSA签名（P0-4: 由 sign_block() 设置）

    # 以下字段由 finalize() 计算，不参与哈希输入
    block_hash: str = field(default="", init=False)

    def __post_init__(self):
        if not self.block_hash:
            self.block_hash = self._compute_hash()

    # P0-4: 出块者签名方法 — proposer 用自己的私钥对区块哈希签名
    # P4-1 安全加固：改为接收 KeyManager 和 agent_id，避免私钥以 hex 字符串传递
    def sign_block(self, key_manager=None, agent_id: str = None) -> None:
        """
        出块者对区块进行签名，确保区块不可篡改且可追溯出块节点

        :param key_manager: KeyManager 实例（持有私钥，不暴露给调用方）
        :param agent_id: 出块者 agent_id，默认使用 self.proposer
        """
        from ..crypto.ecdsa_utils import ECDSAUtils
        try:
            if key_manager is None:
                return
            aid = agent_id or self.proposer
            priv_key = key_manager.get_private_key(aid)
            if priv_key is None:
                logger.warning(f"[Block] 无法获取 {aid} 的私钥，跳过签名")
                return
            # 对区块哈希进行签名
            block_hash_bytes = bytes.fromhex(self.block_hash)
            signature = ECDSAUtils.sign(priv_key, block_hash_bytes)
            self.signature_hex = signature.hex()
            logger.info(
                f"[Block] 出块者签名完成: proposer={self.proposer} "
                f"block_height={self.block_height}"
            )
        except Exception as e:
            # 签名失败不阻塞出块，但记录警告
            logger.warning(f"[Block] 出块者签名失败: {e}")

    def _compute_hash(self) -> str:
        """计算区块哈希（不包含block_hash本身）"""
        data = {
            'block_height': self.block_height,
            'previous_hash': self.previous_hash,
            'timestamp': self.timestamp,
            'proposer': self.proposer,
            'tx_hashes': [tx.tx_id for tx in self.transactions],
            'state_root': self.state_root,
        }
        return hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()

    def compute_state_root(self) -> str:
        """计算状态根：对交易哈希求 Merkle 根（交易默克尔根），作为区块头完整性承诺"""
        tx_hashes = [tx.tx_id for tx in self.transactions]
        if not tx_hashes:
            return "0" * 64
        return compute_merkle_root(tx_hashes)

    def finalize(self) -> str:
        """重新计算 state_root 和区块哈希（在交易和签名确定后调用）"""
        self.state_root = self.compute_state_root()
        self.block_hash = self._compute_hash()
        return self.block_hash

    def to_dict(self) -> Dict:
        return {
            'block_height': self.block_height,
            'previous_hash': self.previous_hash,
            'timestamp': self.timestamp,
            'proposer': self.proposer,
            'transactions': [tx.to_dict() for tx in self.transactions],
            'state_root': self.state_root,
            'signature_hex': self.signature_hex,
            'block_hash': self.block_hash,
        }

    @staticmethod
    def from_dict(d: Dict) -> 'Block':
        txs = [Transaction.from_dict(t) for t in d.get('transactions', [])]
        b = Block(
            block_height=d['block_height'],
            previous_hash=d['previous_hash'],
            timestamp=d['timestamp'],
            proposer=d['proposer'],
            transactions=txs,
            state_root=d['state_root'],
            signature_hex=d.get('signature_hex', ''),
        )
        b.block_hash = d.get('block_hash', b._compute_hash())
        return b

    def is_valid_chain_link(self, prev_block: 'Block') -> bool:
        """验证与前一区块的链式连接有效性"""
        return (
            self.block_height == prev_block.block_height + 1 and
            self.previous_hash == prev_block.block_hash
        )

    @staticmethod
    def create_genesis() -> 'Block':
        """
        创建创世区块
        P2-14 修复：使用固定时间戳 0，确保每次运行创世区块哈希确定性，
        方便竞赛演示中比对不同运行结果
        """
        genesis = Block(
            block_height=0,
            previous_hash="0" * 64,
            timestamp=0,          # P2-14: 固定时间戳，保证确定性
            proposer="genesis",
            transactions=[],
            state_root="0" * 64,
            signature_hex="",
        )
        return genesis

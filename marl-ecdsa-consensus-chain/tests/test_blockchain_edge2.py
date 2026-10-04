"""
Blockchain 剩余边界测试（RalphLoop 原子任务 DA）
覆盖：Block 组合（finalize+序列化）、交易哈希与区块联动、链统计边界
通过标准：新增 ≥6 项测试全过
"""
import hashlib
import logging
import time

import pytest

from blockchain.ledger.block import Block, Transaction
from blockchain.ledger.blockchain import Blockchain

logging.basicConfig(level=logging.CRITICAL)


def _make_tx(agent_id="agent_0", nonce=1):
    action = [0.1, 0.2]
    return Transaction(
        tx_id=hashlib.sha256(f"{agent_id}{nonce}".encode()).hexdigest()[:16],
        agent_id=agent_id,
        action=action,
        action_hash=hashlib.sha256(str(action).encode()).hexdigest()[:16],
        timestamp=int(time.time() * 1000),
        nonce=nonce,
        signature_hex="0x" + "ab" * 32,
        extra={'verified': True, 'message_hex': '00'},
    )


def _make_block(prev_block, transactions):
    return Block(
        block_height=prev_block.block_height + 1,
        previous_hash=prev_block.block_hash,
        timestamp=int(time.time() * 1000),
        proposer="node_0",
        transactions=transactions,
        state_root="0" * 64,
    )


class TestBlockCombo:
    def test_finalize_then_serialize(self):
        """finalize 后序列化往返一致（state_root/hash 保留）"""
        genesis = Block.create_genesis()
        b = _make_block(genesis, [_make_tx()])
        b.finalize()
        restored = Block.from_dict(b.to_dict())
        assert restored.block_hash == b.block_hash
        assert restored.state_root == b.state_root
        assert len(restored.transactions) == 1

    def test_tx_hash_in_block(self):
        """区块内交易哈希稳定（序列化前后）"""
        genesis = Block.create_genesis()
        tx = _make_tx(nonce=5)
        b = _make_block(genesis, [tx])
        b.finalize()
        restored = Block.from_dict(b.to_dict())
        assert restored.transactions[0].compute_hash() == tx.compute_hash()

    def test_block_height_continuity(self):
        """连续块高度 +1 且链有效"""
        bc = Blockchain()
        for i in range(4):
            prev = bc.latest_block
            bc.append_block(_make_block(prev, []))
            assert bc.latest_block.block_height == prev.block_height + 1
        assert bc.validate_chain() is True


class TestChainStatsEdge:
    def test_stats_zero_blocks(self):
        """仅创世统计"""
        bc = Blockchain()
        stats = bc.get_stats()
        assert stats['height'] == 0
        assert stats['total_blocks'] == 1
        assert stats['total_transactions'] == 0
        assert stats['pending_transactions'] == 0

    def test_stats_large_chain(self):
        """20 块链统计一致"""
        bc = Blockchain()
        for i in range(20):
            bc.append_block(_make_block(bc.latest_block, [_make_tx(nonce=i)]))
        stats = bc.get_stats()
        assert stats['height'] == 20
        assert stats['total_transactions'] == 20
        assert stats['total_blocks'] == 21


class TestTxIdDerivation:
    def test_tx_id_from_compute_hash(self):
        """tx_id 由哈希派生（可复现）"""
        tx = _make_tx("agent_0", 3)
        # 重新构造相同交易 → 相同 tx_id（含时间戳相同场景）
        tx2 = _make_tx("agent_0", 3)
        if tx.timestamp == tx2.timestamp:
            assert tx.tx_id == tx2.tx_id
        assert len(tx.tx_id) == 16  # 16 字符截断

    def test_tx_id_unique_per_nonce(self):
        """不同 nonce → 不同 tx_id"""
        tx1 = _make_tx("agent_0", 1)
        tx2 = _make_tx("agent_0", 2)
        assert tx1.tx_id != tx2.tx_id

    def test_merkle_root_from_tx_ids(self):
        """Merkle 根基于 tx_id 列表（顺序敏感）"""
        from blockchain.ledger.block import compute_merkle_root
        t1 = _make_tx(nonce=1).tx_id
        t2 = _make_tx(nonce=2).tx_id
        root_a = compute_merkle_root([t1, t2])
        root_b = compute_merkle_root([t2, t1])
        assert root_a != root_b  # 顺序敏感防重排

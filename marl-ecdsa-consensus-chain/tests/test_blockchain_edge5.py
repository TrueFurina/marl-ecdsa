"""
Blockchain 剩余边界测试（RalphLoop 原子任务 DG）
覆盖：Block 组合、交易哈希派生、链统计边界（此前未单点覆盖）
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


class TestBlockTxCombo:
    def test_tx_id_in_block_stable(self):
        """区块内交易 tx_id 稳定（序列化前后）"""
        genesis = Block.create_genesis()
        tx = _make_tx(nonce=3)
        b = _make_block(genesis, [tx])
        b.finalize()
        restored = Block.from_dict(b.to_dict())
        assert restored.transactions[0].tx_id == tx.tx_id

    def test_block_hash_includes_tx_ids(self):
        """区块哈希依赖交易 tx_id 列表（交易变化 → 哈希变化）"""
        genesis = Block.create_genesis()
        b1 = _make_block(genesis, [_make_tx(nonce=1)])
        b2 = _make_block(genesis, [_make_tx(nonce=2)])
        # 同高度/同 prev/不同交易 → 哈希不同（finalize 后 state_root 不同）
        b1.finalize()
        b2.finalize()
        assert b1.block_hash != b2.block_hash

    def test_genesis_constant_hash(self):
        """创世哈希恒定（固定时间戳 0）"""
        g1 = Block.create_genesis()
        g2 = Block.create_genesis()
        assert g1.block_hash == g2.block_hash
        assert g1.timestamp == 0


class TestTxDerivation:
    def test_tx_id_prefix_of_hash(self):
        """tx_id 由消息哈希派生（16 字符）"""
        tx = _make_tx()
        assert len(tx.tx_id) == 16
        assert all(c in '0123456789abcdef' for c in tx.tx_id)

    def test_tx_hash_deterministic_same_ts(self):
        """同 timestamp 交易哈希确定"""
        tx1 = _make_tx("agent_0", 1)
        tx1.timestamp = 1000
        tx2 = _make_tx("agent_0", 1)
        tx2.timestamp = 1000
        assert tx1.compute_hash() == tx2.compute_hash()

    def test_tx_hash_differs_by_agent(self):
        """不同 agent → 不同交易哈希"""
        tx1 = _make_tx("agent_0", 1)
        tx1.timestamp = 1000
        tx2 = _make_tx("agent_1", 1)
        tx2.timestamp = 1000
        assert tx1.compute_hash() != tx2.compute_hash()


class TestStatsEdge:
    def test_stats_latest_hash_changes(self):
        """追加后 latest_hash 变化"""
        bc = Blockchain()
        h0 = bc.get_stats()['latest_hash']
        bc.append_block(_make_block(bc.latest_block, []))
        h1 = bc.get_stats()['latest_hash']
        assert h0 != h1

    def test_stats_blocks_height_relation(self):
        """total_blocks = height + 1（恒成立）"""
        bc = Blockchain()
        for i in range(3):
            bc.append_block(_make_block(bc.latest_block, []))
        stats = bc.get_stats()
        assert stats['total_blocks'] == stats['height'] + 1

    def test_pending_stats_with_pool(self):
        """有交易池时 pending 统计正确"""
        bc = Blockchain()
        bc.add_transaction(_make_tx(nonce=1))
        bc.add_transaction(_make_tx(nonce=2))
        stats = bc.get_stats()
        assert stats['pending_transactions'] == 2
        assert stats['total_transactions'] == 0  # 未上链不计

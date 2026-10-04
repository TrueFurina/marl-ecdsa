"""
Blockchain 剩余边界测试（RalphLoop 原子任务 CS）
覆盖：交易池容量边界、区块查询组合、哈希验证边界（此前未单点覆盖）
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


class TestTxPoolCapacity:
    def test_capacity_edge_reject(self):
        """交易池满前最后 1 个加入，满后拒绝"""
        bc = Blockchain()
        # 填满
        for i in range(bc.MAX_TX_POOL_SIZE):
            assert bc.add_transaction(_make_tx(nonce=i)) is True
        # 超限拒绝
        assert bc.add_transaction(_make_tx(nonce=999999)) is False
        assert bc.get_tx_pool_size() == bc.MAX_TX_POOL_SIZE

    def test_capacity_after_append_frees(self):
        """上链释放空间后可继续加入"""
        bc = Blockchain()
        txs = [_make_tx(nonce=i) for i in range(100)]
        for tx in txs:
            bc.add_transaction(tx)
        # 上链 50 笔 → 池剩 50
        bc.append_block(_make_block(bc.latest_block, txs[:50]))
        assert bc.get_tx_pool_size() == 50
        # 可继续加入
        assert bc.add_transaction(_make_tx(nonce=200)) is True


class TestBlockQueryEdge:
    def test_get_block_negative_none(self):
        bc = Blockchain()
        assert bc.get_block(-1) is None

    def test_get_blocks_from_negative_all(self):
        """负起始 → 全部（切片语义）"""
        bc = Blockchain()
        for i in range(3):
            bc.append_block(_make_block(bc.latest_block, []))
        assert len(bc.get_blocks_from(-99)) == 4  # 创世 + 3

    def test_get_blocks_from_zero_includes_genesis(self):
        bc = Blockchain()
        blocks = bc.get_blocks_from(0)
        assert blocks[0].block_height == 0
        assert blocks[0].previous_hash == "0" * 64  # 创世


class TestHashValidation:
    def test_genesis_hash_deterministic(self):
        """创世区块哈希确定（P2-14 固定时间戳）"""
        g1 = Block.create_genesis()
        g2 = Block.create_genesis()
        assert g1.block_hash == g2.block_hash

    def test_append_keeps_chain_valid(self):
        """连续追加后链始终有效"""
        bc = Blockchain()
        for i in range(5):
            bc.append_block(_make_block(bc.latest_block, [_make_tx(nonce=i)]))
        assert bc.validate_chain() is True

    def test_rejected_block_does_not_break_chain(self):
        """拒绝坏块后链仍有效（隔离性）"""
        bc = Blockchain()
        bc.append_block(_make_block(bc.latest_block, []))
        # 坏块（prev_hash 错误）
        bad = Block(
            block_height=2, previous_hash="0" * 64,
            timestamp=int(time.time() * 1000),
            proposer="node_0", transactions=[], state_root="0" * 64,
        )
        assert bc.append_block(bad) is False
        assert bc.height == 1  # 链未增长
        assert bc.validate_chain() is True  # 原链仍有效


class TestStatsEdge:
    def test_stats_after_reject(self):
        """拒绝区块后统计不变"""
        bc = Blockchain()
        genesis = bc.latest_block
        bad = Block(
            block_height=1, previous_hash="0" * 64,
            timestamp=int(time.time() * 1000),
            proposer="node_0", transactions=[], state_root="0" * 64,
        )
        bc.append_block(bad)
        stats = bc.get_stats()
        assert stats['height'] == 0
        assert stats['total_blocks'] == 1  # 仅创世
        assert stats['total_transactions'] == 0

"""
Blockchain 剩余边界测试（RalphLoop 原子任务 CY）
覆盖：Block finalize/state_root 组合、交易哈希、链统计边界（此前未单点覆盖）
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


class TestBlockFinalize:
    def test_finalize_updates_state_root(self):
        """finalize 更新 state_root（含交易时非全零）"""
        genesis = Block.create_genesis()
        b = _make_block(genesis, [_make_tx()])
        assert b.state_root == "0" * 64  # 初始全零
        b.finalize()
        assert b.state_root != "0" * 64  # 更新为 Merkle 根

    def test_finalize_returns_hash(self):
        """finalize 返回计算后哈希"""
        genesis = Block.create_genesis()
        b = _make_block(genesis, [_make_tx()])
        h = b.finalize()
        assert h == b.block_hash
        assert len(h) == 64

    def test_finalize_twice_idempotent(self):
        """finalize 幂等（同状态二次调用哈希一致）"""
        genesis = Block.create_genesis()
        b = _make_block(genesis, [_make_tx()])
        h1 = b.finalize()
        h2 = b.finalize()
        assert h1 == h2


class TestStateRoot:
    def test_state_root_empty_block_zeros(self):
        """空交易区块 state_root 全零"""
        genesis = Block.create_genesis()
        b = _make_block(genesis, [])
        assert b.compute_state_root() == "0" * 64

    def test_state_root_changes_with_tx(self):
        """不同交易 → 不同 state_root"""
        genesis = Block.create_genesis()
        b1 = _make_block(genesis, [_make_tx(nonce=1)])
        b2 = _make_block(genesis, [_make_tx(nonce=2)])
        assert b1.compute_state_root() != b2.compute_state_root()


class TestTxHash:
    def test_tx_hash_unique_by_nonce(self):
        """不同 nonce → 不同交易哈希"""
        tx1 = _make_tx("agent_0", 1)
        tx2 = _make_tx("agent_0", 2)
        if tx1.timestamp == tx2.timestamp:
            assert tx1.compute_hash() != tx2.compute_hash()

    def test_tx_hash_32_bytes(self):
        """交易哈希 64 hex（32 字节）"""
        tx = _make_tx()
        assert len(tx.compute_hash()) == 64


class TestChainStats:
    def test_stats_consistent_multi_blocks(self):
        """多块统计一致性（高度/块数/交易数/待处理）"""
        bc = Blockchain()
        for i in range(6):
            bc.append_block(_make_block(bc.latest_block, [_make_tx(nonce=i)]))
        stats = bc.get_stats()
        assert stats['height'] == 6
        assert stats['total_blocks'] == 7  # 含创世
        assert stats['total_transactions'] == 6
        assert stats['pending_transactions'] == 0

    def test_stats_latest_hash_preview(self):
        """latest_hash 预览格式（16 hex + ...）"""
        bc = Blockchain()
        stats = bc.get_stats()
        assert stats['latest_hash'].endswith('...')
        assert len(stats['latest_hash']) == 19

    def test_block_hash_deterministic_create(self):
        """创世哈希确定性（固定时间戳）"""
        assert Block.create_genesis().block_hash == Block.create_genesis().block_hash

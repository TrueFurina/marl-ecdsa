"""
Blockchain get_stats 边界测试（RalphLoop 原子任务 W）
覆盖：统计结构、区块/交易累计、交易池待处理、创世初始态
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


class TestInitialStats:
    def test_stats_structure(self):
        bc = Blockchain()
        stats = bc.get_stats()
        for key in ['height', 'total_blocks', 'total_transactions',
                    'latest_hash', 'pending_transactions']:
            assert key in stats

    def test_genesis_stats(self):
        bc = Blockchain()
        stats = bc.get_stats()
        assert stats['height'] == 0
        assert stats['total_blocks'] == 1  # 含创世区块
        assert stats['total_transactions'] == 0
        assert stats['pending_transactions'] == 0


class TestStatsAfterAppend:
    def test_stats_after_block_append(self):
        bc = Blockchain()
        genesis = bc.latest_block
        tx = _make_tx()
        block = _make_block(genesis, [tx])
        bc.append_block(block)
        stats = bc.get_stats()
        assert stats['height'] == 1
        assert stats['total_blocks'] == 2
        assert stats['total_transactions'] == 1

    def test_stats_after_multiple_blocks(self):
        bc = Blockchain()
        for i in range(3):
            genesis = bc.latest_block
            tx = _make_tx(nonce=i)
            bc.append_block(_make_block(genesis, [tx]))
        stats = bc.get_stats()
        assert stats['height'] == 3
        assert stats['total_transactions'] == 3

    def test_latest_hash_preview(self):
        bc = Blockchain()
        stats = bc.get_stats()
        assert stats['latest_hash'].endswith('...')
        assert len(stats['latest_hash']) == 19  # 16 + '...'


class TestStatsWithPendingTx:
    def test_stats_pending_transactions(self):
        bc = Blockchain()
        bc.add_transaction(_make_tx())
        bc.add_transaction(_make_tx(nonce=2))
        stats = bc.get_stats()
        assert stats['pending_transactions'] == 2
        # 待处理交易不计入 total_transactions（尚未上链）
        assert stats['total_transactions'] == 0

    def test_stats_pending_cleared_after_append(self):
        bc = Blockchain()
        tx = _make_tx()
        bc.add_transaction(tx)
        genesis = bc.latest_block
        bc.append_block(_make_block(genesis, [tx]))
        stats = bc.get_stats()
        assert stats['pending_transactions'] == 0
        assert stats['total_transactions'] == 1


class TestGetBlocks:
    def test_get_blocks_from_range(self):
        bc = Blockchain()
        genesis = bc.latest_block
        bc.append_block(_make_block(genesis, []))
        bc.append_block(_make_block(bc.latest_block, []))
        blocks = bc.get_blocks_from(1)
        assert len(blocks) == 2
        assert blocks[0].block_height == 1

    def test_get_blocks_from_beyond_end(self):
        bc = Blockchain()
        assert bc.get_blocks_from(99) == []

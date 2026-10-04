"""
Blockchain 区块查询边界测试（RalphLoop 原子任务 AU）
覆盖：latest_block、get_block、get_blocks_from、交易池查询边界
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


@pytest.fixture
def chain():
    bc = Blockchain()
    genesis = bc.latest_block
    for i in range(3):
        bc.append_block(_make_block(bc.latest_block, [_make_tx(nonce=i)]))
    return bc


class TestLatestBlock:
    def test_latest_block_returns_last(self, chain):
        assert chain.latest_block.block_height == 3

    def test_latest_block_is_chain_tail(self, chain):
        assert chain.latest_block is chain.get_block(3)


class TestGetBlock:
    def test_get_block_valid(self, chain):
        assert chain.get_block(1).block_height == 1

    def test_get_block_negative_none(self, chain):
        assert chain.get_block(-1) is None

    def test_get_block_beyond_height_none(self, chain):
        assert chain.get_block(99) is None

    def test_get_block_genesis(self, chain):
        assert chain.get_block(0).previous_hash == "0" * 64


class TestGetBlocksFrom:
    def test_get_blocks_from_zero(self, chain):
        blocks = chain.get_blocks_from(0)
        assert len(blocks) == 4  # 创世 + 3

    def test_get_blocks_from_mid(self, chain):
        blocks = chain.get_blocks_from(2)
        assert len(blocks) == 2
        assert blocks[0].block_height == 2

    def test_get_blocks_from_beyond_none(self, chain):
        assert chain.get_blocks_from(99) == []

    def test_get_blocks_from_negative_all(self, chain):
        """负起始高度 → 返回全部（Python 切片语义）"""
        blocks = chain.get_blocks_from(-5)
        assert len(blocks) == 4


class TestTxPoolQueries:
    def test_get_tx_pool_size(self, chain):
        assert chain.get_tx_pool_size() == 0  # 交易已上链

    def test_get_pending_max_count(self):
        bc = Blockchain()
        for i in range(10):
            bc.add_transaction(_make_tx(nonce=i))
        pending = bc.get_pending_transactions(max_count=5)
        assert len(pending) == 5

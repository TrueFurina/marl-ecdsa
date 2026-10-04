"""
Blockchain 剩余边界测试（RalphLoop 原子任务 CW）
覆盖：交易池批量边界、区块查询组合、持久化+交易池+查询三方联动
通过标准：新增 ≥6 项测试全过
"""
import hashlib
import json
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


class TestTxPoolBatch:
    def test_batch_add_unique(self):
        """批量加入唯一交易"""
        bc = Blockchain()
        txs = [_make_tx(nonce=i) for i in range(50)]
        added = sum(1 for tx in txs if bc.add_transaction(tx))
        assert added == 50
        assert bc.get_tx_pool_size() == 50

    def test_batch_with_duplicates(self):
        """批量含重复 → 去重只加一次"""
        bc = Blockchain()
        tx = _make_tx(nonce=1)
        bc.add_transaction(tx)
        bc.add_transaction(tx)  # 重复
        bc.add_transaction(_make_tx(nonce=2))
        assert bc.get_tx_pool_size() == 2  # 去重后

    def test_pending_order_preserved(self):
        """交易池 FIFO 顺序保持"""
        bc = Blockchain()
        txs = [_make_tx(nonce=i) for i in range(5)]
        for tx in txs:
            bc.add_transaction(tx)
        pending = bc.get_pending_transactions()
        assert [t.nonce for t in pending] == [0, 1, 2, 3, 4]


class TestQueryCombo:
    def test_find_after_multiple_blocks(self):
        """多块后 find_transaction 可查任意块交易"""
        bc = Blockchain()
        txs = [_make_tx(nonce=i) for i in range(10)]
        for i in range(0, 10, 2):
            bc.append_block(_make_block(bc.latest_block, txs[i:i + 2]))
        for tx in txs:
            assert bc.find_transaction(tx.tx_id) is not None

    def test_agent_query_limit(self):
        """按 agent 查询 limit 截断"""
        bc = Blockchain()
        for i in range(10):
            bc.append_block(_make_block(bc.latest_block, [_make_tx("agent_0", i)]))
        txs = bc.get_agent_transactions("agent_0", limit=4)
        assert len(txs) == 4


class TestPersistTripleCombo:
    def test_persist_pool_chain_query(self, tmp_path):
        """持久化+交易池+查询三方联动"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        # 2 笔上链 + 1 笔留池
        on_chain = _make_tx(nonce=1)
        in_pool = _make_tx(nonce=2)
        bc1.add_transaction(on_chain)
        bc1.add_transaction(in_pool)
        bc1.append_block(_make_block(bc1.latest_block, [on_chain]))
        # 重载
        bc2 = Blockchain(persist_path=str(persist))
        assert bc2.find_transaction(on_chain.tx_id) is not None  # 上链持久化
        assert bc2.find_transaction(in_pool.tx_id) is None  # 池中未持久化
        assert bc2.get_tx_pool_size() == 0
        assert bc2.height == 1

    def test_persist_reload_then_append(self, tmp_path):
        """重载后继续追加新块"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        bc1.append_block(_make_block(bc1.latest_block, []))
        bc2 = Blockchain(persist_path=str(persist))
        bc2.append_block(_make_block(bc2.latest_block, [_make_tx(nonce=9)]))
        assert bc2.height == 2
        assert bc2.validate_chain() is True
        assert bc2.find_transaction(_make_tx(nonce=9).tx_id) is not None


class TestChainValidity:
    def test_valid_after_rejects(self):
        """多次拒绝坏块后链仍有效"""
        bc = Blockchain()
        bc.append_block(_make_block(bc.latest_block, []))
        for _ in range(3):
            bad = Block(
                block_height=9, previous_hash="0" * 64,
                timestamp=int(time.time() * 1000),
                proposer="node_0", transactions=[], state_root="0" * 64,
            )
            bc.append_block(bad)
        assert bc.height == 1  # 仅 1 个有效块
        assert bc.validate_chain() is True

    def test_genesis_alone_valid(self):
        """仅创世链有效"""
        bc = Blockchain()
        assert bc.validate_chain() is True
        assert bc.get_stats()['total_blocks'] == 1

"""
Blockchain 交易池边界测试（RalphLoop 原子任务 BZ）
覆盖：加入/去重/容量上限/查询截断/上链移除
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


class TestAddTransaction:
    def test_add_returns_true(self):
        bc = Blockchain()
        assert bc.add_transaction(_make_tx(nonce=1)) is True
        assert bc.get_tx_pool_size() == 1

    def test_duplicate_rejected(self):
        """相同 tx_id 重复加入 → False（去重）"""
        bc = Blockchain()
        tx = _make_tx(nonce=1)
        assert bc.add_transaction(tx) is True
        assert bc.add_transaction(tx) is False
        assert bc.get_tx_pool_size() == 1  # 未重复加入

    def test_different_tx_both_added(self):
        """不同 tx_id → 均加入"""
        bc = Blockchain()
        bc.add_transaction(_make_tx(nonce=1))
        bc.add_transaction(_make_tx(nonce=2))
        assert bc.get_tx_pool_size() == 2

    def test_capacity_limit_rejects(self):
        """交易池满（MAX_TX_POOL_SIZE）→ 拒绝新交易"""
        bc = Blockchain()
        # 塞满交易池（容量上限 10000）
        for i in range(bc.MAX_TX_POOL_SIZE):
            bc.add_transaction(_make_tx(nonce=i))
        assert bc.get_tx_pool_size() == bc.MAX_TX_POOL_SIZE
        # 超限交易被拒绝
        assert bc.add_transaction(_make_tx(nonce=999999)) is False


class TestGetPending:
    def test_max_count_truncates(self):
        bc = Blockchain()
        for i in range(10):
            bc.add_transaction(_make_tx(nonce=i))
        pending = bc.get_pending_transactions(max_count=5)
        assert len(pending) == 5

    def test_pending_returns_copy(self):
        """get_pending_transactions 返回副本（修改不影响内部）"""
        bc = Blockchain()
        bc.add_transaction(_make_tx(nonce=1))
        pending = bc.get_pending_transactions()
        pending.clear()
        assert bc.get_tx_pool_size() == 1  # 内部未变

    def test_empty_pool(self):
        bc = Blockchain()
        assert bc.get_pending_transactions() == []
        assert bc.get_tx_pool_size() == 0


class TestPoolLifecycle:
    def test_append_removes_pool_tx(self):
        """区块上链 → 对应交易从池移除"""
        bc = Blockchain()
        tx = _make_tx(nonce=1)
        bc.add_transaction(tx)
        bc.append_block(_make_block(bc.latest_block, [tx]))
        assert bc.get_tx_pool_size() == 0

    def test_append_keeps_other_tx(self):
        """区块上链仅移除包含的交易，其他保留"""
        bc = Blockchain()
        tx1 = _make_tx(nonce=1)
        tx2 = _make_tx(nonce=2)
        bc.add_transaction(tx1)
        bc.add_transaction(tx2)
        bc.append_block(_make_block(bc.latest_block, [tx1]))
        assert bc.get_tx_pool_size() == 1  # tx2 仍在池
        pending = bc.get_pending_transactions()
        assert pending[0].tx_id == tx2.tx_id

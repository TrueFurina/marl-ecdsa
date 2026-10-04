"""
Blockchain 持久化+交易池组合测试（RalphLoop 原子任务 CH）
覆盖：持久化链与交易池的交互（重载后交易池、上链后池清理持久化）
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


class TestPersistAndTxPool:
    def test_reload_does_not_persist_pool(self, tmp_path):
        """交易池不随链持久化（重载后池为空，交易须重新添加）"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        tx = _make_tx(nonce=1)
        bc1.add_transaction(tx)  # 只入池不上链
        bc2 = Blockchain(persist_path=str(persist))
        assert bc2.get_tx_pool_size() == 0  # 池状态不持久化
        assert bc2.height == 0

    def test_reload_then_add_tx(self, tmp_path):
        """重载后交易池可正常使用"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        bc1.append_block(_make_block(bc1.latest_block, []))
        bc2 = Blockchain(persist_path=str(persist))
        tx = _make_tx(nonce=5)
        assert bc2.add_transaction(tx) is True
        assert bc2.get_tx_pool_size() == 1
        assert bc2.height == 1  # 链状态保留


class TestPoolAndChainPersist:
    def test_pool_to_chain_then_reload(self, tmp_path):
        """入池→上链→重载：交易在链上可查"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        tx = _make_tx(nonce=3)
        bc1.add_transaction(tx)
        bc1.append_block(_make_block(bc1.latest_block, [tx]))
        bc2 = Blockchain(persist_path=str(persist))
        assert bc2.find_transaction(tx.tx_id) is not None  # 上链交易已持久化
        assert bc2.get_tx_pool_size() == 0

    def test_pool_remaining_after_partial_append(self, tmp_path):
        """部分上链：池中剩余交易不持久化，上链交易可查"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        tx1 = _make_tx(nonce=1)
        tx2 = _make_tx(nonce=2)
        bc1.add_transaction(tx1)
        bc1.add_transaction(tx2)
        bc1.append_block(_make_block(bc1.latest_block, [tx1]))  # 仅 tx1 上链
        bc2 = Blockchain(persist_path=str(persist))
        assert bc2.find_transaction(tx1.tx_id) is not None  # 上链的持久化
        assert bc2.find_transaction(tx2.tx_id) is None  # 池中未上链不持久化
        assert bc2.get_tx_pool_size() == 0


class TestTxPoolLifecycleWithPersist:
    def test_reload_append_then_query(self, tmp_path):
        """重载→追加新块→全链查询一致"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        bc1.append_block(_make_block(bc1.latest_block, [_make_tx(nonce=1)]))
        bc2 = Blockchain(persist_path=str(persist))
        tx_new = _make_tx(nonce=2)
        bc2.append_block(_make_block(bc2.latest_block, [tx_new]))
        assert bc2.height == 2
        assert bc2.find_transaction(tx_new.tx_id) is not None
        assert bc2.validate_chain() is True

    def test_pool_limit_independent_of_persist(self):
        """交易池容量上限与持久化无关（内存态）"""
        bc = Blockchain()
        for i in range(5):
            bc.add_transaction(_make_tx(nonce=i))
        assert bc.get_tx_pool_size() == 5
        # 池状态内存态：新实例不受影响
        bc2 = Blockchain()
        assert bc2.get_tx_pool_size() == 0

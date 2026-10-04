"""
Blockchain 剩余边界测试（RalphLoop 原子任务 DE）
覆盖：Block 序列化+哈希组合、链统计持久化、交易池容量边界
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


class TestBlockSerializeCombo:
    def test_serialize_restore_transactions(self):
        """序列化恢复保留全部交易"""
        genesis = Block.create_genesis()
        txs = [_make_tx(nonce=i) for i in range(3)]
        b = _make_block(genesis, txs)
        b.finalize()
        restored = Block.from_dict(b.to_dict())
        assert len(restored.transactions) == 3
        assert [t.tx_id for t in restored.transactions] == [t.tx_id for t in txs]

    def test_serialize_restore_proposer(self):
        """序列化恢复保留 proposer"""
        genesis = Block.create_genesis()
        b = _make_block(genesis, [])
        restored = Block.from_dict(b.to_dict())
        assert restored.proposer == "node_0"

    def test_serialize_json_roundtrip(self):
        """Block to_dict → JSON → from_dict 往返"""
        genesis = Block.create_genesis()
        b = _make_block(genesis, [_make_tx()])
        b.finalize()
        d = json.loads(json.dumps(b.to_dict()))
        restored = Block.from_dict(d)
        assert restored.block_hash == b.block_hash


class TestChainStatsPersist:
    def test_stats_persist_equal(self, tmp_path):
        """持久化前后 get_stats 完全一致"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        for i in range(5):
            bc1.append_block(_make_block(bc1.latest_block, [_make_tx(nonce=i)]))
        s1 = bc1.get_stats()
        bc2 = Blockchain(persist_path=str(persist))
        assert bc2.get_stats() == s1

    def test_stats_height_after_append(self):
        """追加后高度统计正确"""
        bc = Blockchain()
        bc.append_block(_make_block(bc.latest_block, []))
        bc.append_block(_make_block(bc.latest_block, [_make_tx()]))
        stats = bc.get_stats()
        assert stats['height'] == 2
        assert stats['total_transactions'] == 1


class TestTxPoolCapacity:
    def test_pool_capacity_reject_at_limit(self):
        """交易池满后拒绝（容量边界）"""
        bc = Blockchain()
        for i in range(bc.MAX_TX_POOL_SIZE):
            bc.add_transaction(_make_tx(nonce=i))
        assert bc.add_transaction(_make_tx(nonce=999999)) is False
        assert bc.get_tx_pool_size() == bc.MAX_TX_POOL_SIZE

    def test_pool_capacity_after_append_frees(self):
        """上链释放空间后可继续加入"""
        bc = Blockchain()
        txs = [_make_tx(nonce=i) for i in range(30)]
        for tx in txs:
            bc.add_transaction(tx)
        bc.append_block(_make_block(bc.latest_block, txs[:15]))
        assert bc.get_tx_pool_size() == 15
        assert bc.add_transaction(_make_tx(nonce=100)) is True

    def test_pool_order_fifo(self):
        """交易池 FIFO 顺序"""
        bc = Blockchain()
        txs = [_make_tx(nonce=i) for i in range(4)]
        for tx in txs:
            bc.add_transaction(tx)
        pending = bc.get_pending_transactions()
        assert [t.nonce for t in pending] == [0, 1, 2, 3]

"""
Blockchain 剩余边界测试（RalphLoop 原子任务 DI）
覆盖：Block 组合（finalize+序列化）、交易池批量边界、链统计持久化
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
    def test_finalize_restore_roundtrip(self):
        """finalize 后序列化恢复一致"""
        genesis = Block.create_genesis()
        b = _make_block(genesis, [_make_tx()])
        b.finalize()
        restored = Block.from_dict(b.to_dict())
        assert restored.block_hash == b.block_hash
        assert restored.state_root == b.state_root

    def test_merkle_root_tx_order(self):
        """Merkle 根交易顺序敏感"""
        from blockchain.ledger.block import compute_merkle_root
        r1 = compute_merkle_root(["a" * 64, "b" * 64])
        r2 = compute_merkle_root(["b" * 64, "a" * 64])
        assert r1 != r2

    def test_genesis_timestamp_zero(self):
        """创世时间戳固定 0（确定性）"""
        g = Block.create_genesis()
        assert g.timestamp == 0


class TestTxPoolBatch:
    def test_batch_unique_txs(self):
        """批量唯一交易全部加入"""
        bc = Blockchain()
        txs = [_make_tx(nonce=i) for i in range(20)]
        added = sum(1 for tx in txs if bc.add_transaction(tx))
        assert added == 20
        assert bc.get_tx_pool_size() == 20

    def test_batch_mixed_duplicates(self):
        """批量含重复 → 去重"""
        bc = Blockchain()
        tx1 = _make_tx(nonce=1)
        tx2 = _make_tx(nonce=2)
        bc.add_transaction(tx1)
        bc.add_transaction(tx1)  # 重复
        bc.add_transaction(tx2)
        assert bc.get_tx_pool_size() == 2

    def test_pending_slice(self):
        """get_pending max_count 截断"""
        bc = Blockchain()
        for i in range(10):
            bc.add_transaction(_make_tx(nonce=i))
        pending = bc.get_pending_transactions(max_count=3)
        assert len(pending) == 3


class TestStatsPersist:
    def test_stats_equal_after_reload(self, tmp_path):
        """重载后统计一致"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        for i in range(4):
            bc1.append_block(_make_block(bc1.latest_block, [_make_tx(nonce=i)]))
        s1 = bc1.get_stats()
        bc2 = Blockchain(persist_path=str(persist))
        assert bc2.get_stats() == s1

    def test_stats_height_blocks(self):
        """高度与块数关系"""
        bc = Blockchain()
        bc.append_block(_make_block(bc.latest_block, []))
        stats = bc.get_stats()
        assert stats['height'] == 1
        assert stats['total_blocks'] == 2

    def test_pending_tx_stat(self):
        """待处理交易统计"""
        bc = Blockchain()
        bc.add_transaction(_make_tx(nonce=1))
        assert bc.get_stats()['pending_transactions'] == 1

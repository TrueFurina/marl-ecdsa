"""
Blockchain 剩余边界测试（RalphLoop 原子任务 DC）
覆盖：Block finalize 幂等、Merkle 状态根边界、链统计持久化组合
通过标准：新增 ≥6 项测试全过
"""
import hashlib
import logging
import time

import pytest

from blockchain.ledger.block import Block, Transaction, compute_merkle_root
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


class TestBlockFinalizeEdge:
    def test_finalize_empty_idempotent(self):
        """空交易 finalize 幂等（state_root 恒全零）"""
        genesis = Block.create_genesis()
        b = _make_block(genesis, [])
        h1 = b.finalize()
        h2 = b.finalize()
        assert h1 == h2
        assert b.state_root == "0" * 64

    def test_finalize_then_mutate_tx(self):
        """finalize 后新增交易 → 需重新 finalize（哈希变化）"""
        genesis = Block.create_genesis()
        b = _make_block(genesis, [])
        b.finalize()
        h_before = b.block_hash
        b.transactions.append(_make_tx(nonce=9))
        b.finalize()  # 重新计算
        assert b.block_hash != h_before  # 交易变化 → 哈希变化

    def test_merkle_root_odd_count(self):
        """奇数交易 Merkle 根（末位自配对）"""
        root = compute_merkle_root(["a" * 64, "b" * 64, "c" * 64])
        assert len(root) == 64


class TestChainPersistStats:
    def test_persist_stats_consistent(self, tmp_path):
        """持久化前后统计一致"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        for i in range(4):
            bc1.append_block(_make_block(bc1.latest_block, [_make_tx(nonce=i)]))
        s1 = bc1.get_stats()
        bc2 = Blockchain(persist_path=str(persist))
        s2 = bc2.get_stats()
        assert s1 == s2  # 高度/交易数/待处理一致

    def test_persist_blocks_hashes_stable(self, tmp_path):
        """持久化后区块哈希稳定"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        hashes = []
        for i in range(3):
            bc1.append_block(_make_block(bc1.latest_block, [_make_tx(nonce=i)]))
            hashes.append(bc1.latest_block.block_hash)
        bc2 = Blockchain(persist_path=str(persist))
        for h in range(1, 4):
            assert bc2.get_block(h).block_hash == hashes[h - 1]


class TestTxPoolPersistCombo:
    def test_pool_cleared_after_persist_reload(self, tmp_path):
        """交易池不持久化：重载后池空（需重新添加）"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        tx = _make_tx(nonce=1)
        bc1.add_transaction(tx)
        bc2 = Blockchain(persist_path=str(persist))
        assert bc2.get_tx_pool_size() == 0
        # 重新添加可正常工作
        assert bc2.add_transaction(tx) is True
        assert bc2.get_tx_pool_size() == 1

    def test_pool_to_chain_persist_then_query(self, tmp_path):
        """入池→上链→持久化→重载查询"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        tx = _make_tx(nonce=5)
        bc1.add_transaction(tx)
        bc1.append_block(_make_block(bc1.latest_block, [tx]))
        bc2 = Blockchain(persist_path=str(persist))
        assert bc2.find_transaction(tx.tx_id) is not None
        assert bc2.get_tx_pool_size() == 0


class TestChainContinuity:
    def test_height_increments(self):
        """高度严格递增"""
        bc = Blockchain()
        heights = [0]  # 创世
        for i in range(5):
            bc.append_block(_make_block(bc.latest_block, []))
            heights.append(bc.latest_block.block_height)
        assert heights == [0, 1, 2, 3, 4, 5]

    def test_validate_after_all_ops(self):
        """全操作后链有效"""
        bc = Blockchain()
        txs = [_make_tx(nonce=i) for i in range(6)]
        for tx in txs:
            bc.add_transaction(tx)
        for i in range(0, 6, 2):
            bc.append_block(_make_block(bc.latest_block, txs[i:i + 2]))
        assert bc.validate_chain() is True
        assert bc.get_tx_pool_size() == 0

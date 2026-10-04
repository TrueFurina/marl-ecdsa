"""
Blockchain 剩余边界测试（RalphLoop 原子任务 CU）
覆盖：Block 序列化+哈希组合、交易池与区块联动、持久化+查询组合（此前未单点覆盖）
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


class TestBlockSerializeHash:
    def test_serialize_restore_hash_stable(self):
        """序列化→恢复：哈希与原始一致（finalize 后）"""
        genesis = Block.create_genesis()
        b = _make_block(genesis, [_make_tx()])
        b.finalize()  # 确定 state_root + block_hash
        restored = Block.from_dict(b.to_dict())
        assert restored.block_hash == b.block_hash
        assert restored.state_root == b.state_root

    def test_finalize_changes_hash(self):
        """含交易区块 finalize 后 state_root 更新 → 哈希变化（空交易区块 state_root 恒全零不变）"""
        genesis = Block.create_genesis()
        b = _make_block(genesis, [_make_tx()])  # 含交易
        before = b.block_hash
        b.finalize()
        assert b.block_hash != before  # state_root 全零→Merkle 根 → 哈希变化

    def test_finalize_empty_block_hash_stable(self):
        """空交易区块 finalize 后哈希不变（state_root 恒为全零，契约）"""
        genesis = Block.create_genesis()
        b = _make_block(genesis, [])
        before = b.block_hash
        b.finalize()
        assert b.block_hash == before  # state_root 未变

    def test_block_merkle_with_txs(self):
        """含交易区块 state_root 非全零（Merkle 根）"""
        genesis = Block.create_genesis()
        b = _make_block(genesis, [_make_tx()])
        root = b.compute_state_root()
        assert root != "0" * 64


class TestTxPoolChainLink:
    def test_pool_then_append_then_query(self):
        """入池→上链→查询全链一致"""
        bc = Blockchain()
        tx = _make_tx(nonce=7)
        bc.add_transaction(tx)
        bc.append_block(_make_block(bc.latest_block, [tx]))
        assert bc.get_tx_pool_size() == 0
        assert bc.find_transaction(tx.tx_id) is not None

    def test_pool_duplicate_after_chain(self):
        """上链后同交易再次入池 → 允许（池中无该交易）"""
        bc = Blockchain()
        tx = _make_tx(nonce=1)
        bc.add_transaction(tx)
        bc.append_block(_make_block(bc.latest_block, [tx]))
        # 同交易再次入池（池中已移除）→ 允许
        assert bc.add_transaction(tx) is True


class TestPersistQueryCombo:
    def test_persist_then_find(self, tmp_path):
        """持久化后 find_transaction 可查"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        tx = _make_tx(nonce=3)
        bc1.append_block(_make_block(bc1.latest_block, [tx]))
        bc2 = Blockchain(persist_path=str(persist))
        assert bc2.find_transaction(tx.tx_id) is not None
        assert bc2.height == 1

    def test_persist_then_agent_query(self, tmp_path):
        """持久化后按 agent 查询"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        bc1.append_block(_make_block(bc1.latest_block, [_make_tx("agent_1", 1)]))
        bc2 = Blockchain(persist_path=str(persist))
        txs = bc2.get_agent_transactions("agent_1")
        assert len(txs) == 1
        assert txs[0].agent_id == "agent_1"


class TestChainStatsCombo:
    def test_stats_blocks_txs_consistent(self):
        """多块统计：total_blocks = height+1（含创世）"""
        bc = Blockchain()
        for i in range(5):
            bc.append_block(_make_block(bc.latest_block, [_make_tx(nonce=i)]))
        stats = bc.get_stats()
        assert stats['total_blocks'] == stats['height'] + 1
        assert stats['total_transactions'] == 5

    def test_validate_after_append_all(self):
        """全部追加后链有效"""
        bc = Blockchain()
        for i in range(8):
            bc.append_block(_make_block(bc.latest_block, [_make_tx(nonce=i)]))
        assert bc.validate_chain() is True
        assert bc.height == 8

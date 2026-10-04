"""
Blockchain 剩余边界测试（RalphLoop 原子任务 DK）
覆盖：Block finalize/序列化组合、交易池与区块联动、统计持久化
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
    def test_finalize_restore_stable(self):
        """finalize 后序列化恢复哈希稳定"""
        genesis = Block.create_genesis()
        b = _make_block(genesis, [_make_tx()])
        b.finalize()
        restored = Block.from_dict(b.to_dict())
        assert restored.block_hash == b.block_hash

    def test_merkle_odd_padding(self):
        """奇数交易 Merkle 末位自配对"""
        from blockchain.ledger.block import compute_merkle_root
        root = compute_merkle_root(["a" * 64, "b" * 64, "c" * 64])
        assert len(root) == 64

    def test_genesis_prev_hash_zeros(self):
        """创世 previous_hash 全零"""
        g = Block.create_genesis()
        assert g.previous_hash == "0" * 64


class TestPoolChainCombo:
    def test_pool_to_chain_query(self):
        """入池→上链→查询全链"""
        bc = Blockchain()
        tx = _make_tx(nonce=1)
        bc.add_transaction(tx)
        bc.append_block(_make_block(bc.latest_block, [tx]))
        assert bc.find_transaction(tx.tx_id) is not None
        assert bc.get_tx_pool_size() == 0

    def test_unconfirmed_not_found(self):
        """未上链交易在链上找不到"""
        bc = Blockchain()
        tx = _make_tx(nonce=2)
        bc.add_transaction(tx)
        assert bc.find_transaction(tx.tx_id) is None
        assert bc.get_tx_pool_size() == 1

    def test_partial_append_keeps_pool(self):
        """部分上链保留池中剩余"""
        bc = Blockchain()
        tx1 = _make_tx(nonce=1)
        tx2 = _make_tx(nonce=2)
        bc.add_transaction(tx1)
        bc.add_transaction(tx2)
        bc.append_block(_make_block(bc.latest_block, [tx1]))
        assert bc.get_tx_pool_size() == 1
        assert bc.get_pending_transactions()[0].tx_id == tx2.tx_id


class TestStatsPersist:
    def test_stats_reload_equal(self, tmp_path):
        """重载后统计一致"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        for i in range(3):
            bc1.append_block(_make_block(bc1.latest_block, [_make_tx(nonce=i)]))
        s1 = bc1.get_stats()
        bc2 = Blockchain(persist_path=str(persist))
        assert bc2.get_stats() == s1

    def test_stats_after_reject_unchanged(self):
        """拒绝坏块后统计不变"""
        bc = Blockchain()
        bad = Block(
            block_height=1, previous_hash="0" * 64,
            timestamp=int(time.time() * 1000),
            proposer="node_0", transactions=[], state_root="0" * 64,
        )
        bc.append_block(bad)
        stats = bc.get_stats()
        assert stats['height'] == 0
        assert stats['total_blocks'] == 1

    def test_latest_hash_preview_format(self):
        """latest_hash 预览格式"""
        bc = Blockchain()
        assert bc.get_stats()['latest_hash'].endswith('...')

"""
Blockchain 组合边界测试（RalphLoop 原子任务 CA）
覆盖：持久化+查询+交易池+验证的组合场景（此前各单点覆盖，组合未覆盖）
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


class TestPersistPlusQuery:
    def test_restore_then_find_transaction(self, tmp_path):
        """重载后 find_transaction 仍可查到历史交易"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        tx = _make_tx(nonce=7)
        bc1.append_block(_make_block(bc1.latest_block, [tx]))
        bc2 = Blockchain(persist_path=str(persist))
        found = bc2.find_transaction(tx.tx_id)
        assert found is not None
        assert found.nonce == 7

    def test_restore_then_validate(self, tmp_path):
        """重载后链通过 validate_chain"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        for i in range(4):
            bc1.append_block(_make_block(bc1.latest_block, [_make_tx(nonce=i)]))
        bc2 = Blockchain(persist_path=str(persist))
        assert bc2.validate_chain() is True

    def test_restore_stats_consistent(self, tmp_path):
        """重载后 get_stats 与保存前一致"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        for i in range(3):
            bc1.append_block(_make_block(bc1.latest_block, [_make_tx(nonce=i)]))
        stats_before = bc1.get_stats()
        bc2 = Blockchain(persist_path=str(persist))
        stats_after = bc2.get_stats()
        assert stats_after['height'] == stats_before['height']
        assert stats_after['total_transactions'] == stats_before['total_transactions']


class TestTxPoolPlusAppend:
    def test_pool_to_chain_lifecycle(self):
        """交易池 → 上链 → 查询全链可找到"""
        bc = Blockchain()
        tx = _make_tx(nonce=1)
        bc.add_transaction(tx)
        bc.append_block(_make_block(bc.latest_block, [tx]))
        assert bc.get_tx_pool_size() == 0
        assert bc.find_transaction(tx.tx_id) is not None  # 已上链可查

    def test_unconfirmed_tx_not_in_chain(self):
        """未上链交易在链上找不到（仍在池中）"""
        bc = Blockchain()
        tx = _make_tx(nonce=1)
        bc.add_transaction(tx)
        assert bc.find_transaction(tx.tx_id) is None  # 池中未上链
        assert bc.get_tx_pool_size() == 1

    def test_pending_then_append_multiple(self):
        """多笔交易先入池后批量上链"""
        bc = Blockchain()
        txs = [_make_tx(nonce=i) for i in range(5)]
        for tx in txs:
            bc.add_transaction(tx)
        # 分批上链：块1 含 tx0/tx1，块2 含 tx2/tx3/tx4
        bc.append_block(_make_block(bc.latest_block, txs[:2]))
        bc.append_block(_make_block(bc.latest_block, txs[2:]))
        assert bc.get_tx_pool_size() == 0
        assert bc.get_stats()['total_transactions'] == 5
        assert bc.height == 2


class TestBlockExplorerData:
    def test_blocks_from_zero_full_chain(self):
        """get_blocks_from(0) 返回完整链（含创世）"""
        bc = Blockchain()
        for i in range(3):
            bc.append_block(_make_block(bc.latest_block, []))
        blocks = bc.get_blocks_from(0)
        assert len(blocks) == 4
        assert blocks[0].block_height == 0  # 创世

    def test_chain_continuity_after_restore(self, tmp_path):
        """重载后继续追加 → 全链连续性保持"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        bc1.append_block(_make_block(bc1.latest_block, []))
        bc2 = Blockchain(persist_path=str(persist))
        bc2.append_block(_make_block(bc2.latest_block, []))
        blocks = bc2.get_blocks_from(0)
        for i in range(1, len(blocks)):
            assert blocks[i].is_valid_chain_link(blocks[i - 1]) is True

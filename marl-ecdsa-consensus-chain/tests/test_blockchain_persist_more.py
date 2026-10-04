"""
Blockchain 持久化多块恢复测试（RalphLoop 原子任务 BL）
覆盖：多块多交易恢复、加载后查询一致、加载后继续追加、哈希确定性
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


class TestMultiBlockRestore:
    def test_restore_5_blocks_with_txs(self, tmp_path):
        """5 块含交易 → 重载后块数与交易数一致"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        for i in range(5):
            bc1.append_block(_make_block(bc1.latest_block, [_make_tx(nonce=i)]))
        bc2 = Blockchain(persist_path=str(persist))
        assert bc2.height == 5
        total_txs = sum(len(b.transactions) for b in bc2._chain)
        assert total_txs == 5  # 5 块各 1 交易

    def test_restore_hashes_consistent(self, tmp_path):
        """重载后各区块哈希与保存前一致（确定性）"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        hashes_before = []
        for i in range(3):
            bc1.append_block(_make_block(bc1.latest_block, []))
            hashes_before.append(bc1.latest_block.block_hash)
        bc2 = Blockchain(persist_path=str(persist))
        for h in range(1, 4):
            assert bc2.get_block(h).block_hash == hashes_before[h - 1]

    def test_restore_then_get_block(self, tmp_path):
        """重载后 get_block 查询与保存时一致"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        tx = _make_tx(nonce=7)
        bc1.append_block(_make_block(bc1.latest_block, [tx]))
        bc2 = Blockchain(persist_path=str(persist))
        restored = bc2.get_block(1)
        assert restored.transactions[0].tx_id == tx.tx_id
        assert restored.block_height == 1


class TestRestoreThenAppend:
    def test_append_after_restore(self, tmp_path):
        """重载后链可继续追加（高度从 3 到 4）"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        for i in range(3):
            bc1.append_block(_make_block(bc1.latest_block, []))
        bc2 = Blockchain(persist_path=str(persist))
        bc2.append_block(_make_block(bc2.latest_block, []))
        assert bc2.height == 4
        assert bc2.validate_chain() is True

    def test_append_restored_chain_valid(self, tmp_path):
        """重载+追加后整链仍有效"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        for i in range(2):
            bc1.append_block(_make_block(bc1.latest_block, [_make_tx(nonce=i)]))
        bc2 = Blockchain(persist_path=str(persist))
        bc2.append_block(_make_block(bc2.latest_block, [_make_tx(nonce=9)]))
        assert bc2.validate_chain() is True
        assert bc2.height == 3


class TestPersistFile:
    def test_persist_file_valid_json(self, tmp_path):
        """持久化文件为合法 JSON 数组（区块列表）"""
        persist = tmp_path / "chain.json"
        bc = Blockchain(persist_path=str(persist))
        bc.append_block(_make_block(bc.latest_block, [_make_tx()]))
        data = json.loads(persist.read_text(encoding='utf-8'))
        assert isinstance(data, list)
        assert len(data) == 2  # 创世 + 1

    def test_genesis_only_reload(self, tmp_path):
        """无追加块 → 重载后高度 0（仅创世）"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        bc2 = Blockchain(persist_path=str(persist))
        assert bc2.height == 0
        assert bc2.validate_chain() is True

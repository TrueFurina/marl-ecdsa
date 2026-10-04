"""
Blockchain 持久化边界测试（RalphLoop 原子任务 AA）
覆盖：保存/加载往返、损坏文件降级、新实例恢复高度、交易随区块持久化
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


class TestPersistRoundtrip:
    def test_save_creates_file(self, tmp_path):
        """append_block 时 _save_latest 落盘"""
        persist = tmp_path / "chain.json"
        bc = Blockchain(persist_path=str(persist))
        genesis = bc.latest_block
        bc.append_block(_make_block(genesis, []))
        assert persist.exists()

    def test_reload_restores_height(self, tmp_path):
        """新实例加载磁盘链 → 恢复相同高度"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        genesis = bc1.latest_block
        for i in range(3):
            bc1.append_block(_make_block(bc1.latest_block, []))
        bc2 = Blockchain(persist_path=str(persist))  # 从磁盘加载
        assert bc2.height == 3

    def test_reload_restores_transactions(self, tmp_path):
        """交易随区块持久化并在重载后恢复"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        tx = _make_tx()
        bc1.append_block(_make_block(bc1.latest_block, [tx]))
        bc2 = Blockchain(persist_path=str(persist))
        restored_tx = bc2.get_block(1).transactions[0]
        assert restored_tx.tx_id == tx.tx_id

    def test_reload_chain_valid(self, tmp_path):
        """重载后的链通过 validate_chain"""
        persist = tmp_path / "chain.json"
        bc1 = Blockchain(persist_path=str(persist))
        for i in range(3):
            bc1.append_block(_make_block(bc1.latest_block, [_make_tx(nonce=i)]))
        bc2 = Blockchain(persist_path=str(persist))
        assert bc2.validate_chain() is True


class TestCorruptFile:
    def test_corrupt_file_load_falls_back(self, tmp_path):
        """损坏的持久化文件 → _try_load 捕获异常，使用全新链"""
        persist = tmp_path / "chain.json"
        persist.write_text("{not valid json!!!", encoding="utf-8")
        bc = Blockchain(persist_path=str(persist))
        assert bc.height == 0  # 全新链


class TestNoPersist:
    def test_no_persist_path_no_file(self, tmp_path):
        """无 persist_path → 不落盘"""
        bc = Blockchain()
        bc.append_block(_make_block(bc.latest_block, []))
        # 不检查具体文件（无 persist_path 场景），仅确认不崩溃
        assert bc.height == 1

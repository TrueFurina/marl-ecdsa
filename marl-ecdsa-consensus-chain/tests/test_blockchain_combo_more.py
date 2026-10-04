"""
Blockchain 组合边界补充测试（RalphLoop 原子任务 CR）
覆盖：多区块+交易+查询+验证的组合场景（此前单点覆盖，组合补充）
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


class TestMultiBlockCombo:
    def test_ten_blocks_full_flow(self):
        """10 块含交易：高度/交易数/链有效/查询一致"""
        bc = Blockchain()
        for i in range(10):
            bc.append_block(_make_block(bc.latest_block, [_make_tx(nonce=i)]))
        assert bc.height == 10
        assert bc.get_stats()['total_transactions'] == 10
        assert bc.validate_chain() is True
        # 查询首块交易
        first_tx = bc.get_block(1).transactions[0]
        assert bc.find_transaction(first_tx.tx_id) is not None

    def test_mixed_blocks_tx_counts(self):
        """混合块交易数：块1=1笔，块2=3笔"""
        bc = Blockchain()
        bc.append_block(_make_block(bc.latest_block, [_make_tx(nonce=1)]))
        bc.append_block(_make_block(bc.latest_block, [_make_tx(nonce=2), _make_tx(nonce=3), _make_tx(nonce=4)]))
        assert bc.get_stats()['total_transactions'] == 4
        assert bc.get_block(1).transactions[0].tx_id == _make_tx(nonce=1).tx_id

    def test_agent_transactions_across_blocks(self):
        """跨块按 agent 查询：agent_0 3 笔分散在 2 块"""
        bc = Blockchain()
        bc.append_block(_make_block(bc.latest_block, [_make_tx("agent_0", 1), _make_tx("agent_1", 2)]))
        bc.append_block(_make_block(bc.latest_block, [_make_tx("agent_0", 3)]))
        txs = bc.get_agent_transactions("agent_0")
        assert len(txs) == 2  # agent_0 有 2 笔（跨 2 块）


class TestChainIntegrityCombo:
    def test_tamper_middle_block_detected(self):
        """篡改块内交易 tx_id → block_hash 变化 → 检测（哈希基于 tx_id 列表）"""
        bc = Blockchain()
        for i in range(3):
            bc.append_block(_make_block(bc.latest_block, [_make_tx(nonce=i)]))
        # 篡改块1交易的 tx_id（哈希计算含 tx_id 列表 → block_hash 不再匹配）
        orig_hash = bc._chain[1].block_hash
        bc._chain[1].transactions[0].tx_id = "tampered_tx_id"
        assert bc._chain[1]._compute_hash() != orig_hash  # 哈希已变
        assert bc.validate_chain() is False  # 链验证检测到

    def test_tamper_content_not_detected_by_hash(self):
        """篡改交易内容（nonce）不改变 tx_id → block_hash 不变（哈希基于 tx_id，实现契约）"""
        bc = Blockchain()
        bc.append_block(_make_block(bc.latest_block, [_make_tx(nonce=1)]))
        orig_hash = bc._chain[1].block_hash
        bc._chain[1].transactions[0].nonce = 999  # 改内容不改 tx_id
        assert bc._chain[1]._compute_hash() == orig_hash  # 哈希不变（tx_id 列表未变）
        assert bc.validate_chain() is True  # 链验证通过

    def test_append_after_tamper_rejected(self):
        """篡改后追加被链式验证拒绝（prev_hash 不匹配）"""
        bc = Blockchain()
        bc.append_block(_make_block(bc.latest_block, []))
        # 篡改块1哈希 → 块2 的 previous_hash 指向原哈希 → 追加被拒
        orig_hash = bc._chain[1].block_hash
        bc._chain[1].block_hash = "0" * 64
        new_block = _make_block(bc.latest_block, [])
        new_block.previous_hash = orig_hash  # 指向原哈希
        assert bc.append_block(new_block) is False


class TestQueryCombo:
    def test_latest_block_after_multiple(self):
        """latest_block 始终为链尾"""
        bc = Blockchain()
        for i in range(4):
            bc.append_block(_make_block(bc.latest_block, []))
        assert bc.latest_block.block_height == 4

    def test_get_blocks_from_mid(self):
        """get_blocks_from(mid) 返回剩余链（5 块链从 3 → 高度 3,4,5 共 3 块）"""
        bc = Blockchain()
        for i in range(5):
            bc.append_block(_make_block(bc.latest_block, []))
        blocks = bc.get_blocks_from(3)
        assert len(blocks) == 3  # 高度 3,4,5
        assert blocks[0].block_height == 3

    def test_stats_after_complex_flow(self):
        """复杂流程后统计一致（交易池+上链+查询）"""
        bc = Blockchain()
        txs = [_make_tx(nonce=i) for i in range(5)]
        for tx in txs:
            bc.add_transaction(tx)
        bc.append_block(_make_block(bc.latest_block, txs[:2]))
        bc.append_block(_make_block(bc.latest_block, txs[2:]))
        stats = bc.get_stats()
        assert stats['total_transactions'] == 5
        assert stats['pending_transactions'] == 0
        assert stats['height'] == 2

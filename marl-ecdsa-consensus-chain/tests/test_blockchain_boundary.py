"""
Blockchain 链式校验边界测试（RalphLoop 原子任务 M）
覆盖：区块追加、链式验证失败、哈希不匹配、交易池边界、区块查询
通过标准：新增 ≥6 项测试全过
"""
import copy
import hashlib
import logging
import time

import pytest

from blockchain.ledger.block import Block, Transaction
from blockchain.ledger.blockchain import Blockchain

logging.basicConfig(level=logging.CRITICAL)


def _make_block(prev_block, transactions, proposer="node_0"):
    """构造可追加区块（与既有测试一致的辅助函数）"""
    return Block(
        block_height=prev_block.block_height + 1,
        previous_hash=prev_block.block_hash,
        timestamp=int(time.time() * 1000),
        proposer=proposer,
        transactions=transactions,
        state_root="s" * 64,
    )


def _make_tx(agent_id="agent_0", extra=None):
    action = [0.1, 0.2]
    return Transaction(
        tx_id=hashlib.sha256(f"{agent_id}{time.time()}".encode()).hexdigest()[:16],
        agent_id=agent_id,
        action=action,
        action_hash=hashlib.sha256(str(action).encode()).hexdigest()[:16],
        timestamp=int(time.time() * 1000),
        nonce=1,
        signature_hex="0x" + "ab" * 32,
        extra=extra or {'verified': True, 'message_hex': '00'},
    )


class TestAppendBlock:
    def test_append_valid_block(self):
        bc = Blockchain()
        genesis = bc.latest_block
        block = _make_block(genesis, [])
        assert bc.append_block(block) is True
        assert bc.height == 1

    def test_append_wrong_prev_hash_rejected(self):
        """链式验证失败：previous_hash 不匹配 → 拒绝"""
        bc = Blockchain()
        bad = Block(
            block_height=1,
            previous_hash="0" * 64,  # 错误的前块哈希
            timestamp=int(time.time() * 1000),
            proposer="node_0",
            transactions=[],
            state_root="s" * 64,
        )
        assert bc.append_block(bad) is False
        assert bc.height == 0  # 链未增长

    def test_append_tampered_hash_rejected(self):
        """区块哈希被篡改 → 哈希不匹配拒绝"""
        bc = Blockchain()
        genesis = bc.latest_block
        block = _make_block(genesis, [])
        block.block_hash = "0" * 64  # 篡改哈希
        assert bc.append_block(block) is False


class TestBlockQuery:
    def test_get_block_out_of_range_none(self):
        bc = Blockchain()
        assert bc.get_block(99) is None
        assert bc.get_block(-1) is None

    def test_get_block_valid(self):
        bc = Blockchain()
        genesis = bc.latest_block
        assert bc.get_block(0) is genesis


class TestTxPool:
    def test_add_transaction_to_pool(self):
        bc = Blockchain()
        tx = _make_tx()
        assert bc.add_transaction(tx) is True
        assert bc.get_tx_pool_size() == 1

    def test_tx_pool_capacity_limit(self):
        """交易池容量上限保护（MAX_TX_POOL_SIZE=10000）"""
        bc = Blockchain()
        # 塞入超过上限的交易
        for i in range(bc.MAX_TX_POOL_SIZE + 50):
            action = [float(i)]
            tx = Transaction(
                tx_id=f"tx_{i}",
                agent_id="agent_0",
                action=action,
                action_hash=hashlib.sha256(str(action).encode()).hexdigest()[:16],
                timestamp=int(time.time() * 1000),
                nonce=i,
                signature_hex="0x" + "ab" * 32,
                extra={'verified': True},
            )
            bc.add_transaction(tx)
        assert bc.get_tx_pool_size() <= bc.MAX_TX_POOL_SIZE

    def test_append_block_removes_pool_tx(self):
        """区块上链后，对应交易从交易池移除"""
        bc = Blockchain()
        tx = _make_tx()
        bc.add_transaction(tx)
        genesis = bc.latest_block
        block = _make_block(genesis, [tx])
        assert bc.append_block(block) is True
        assert bc.get_tx_pool_size() == 0  # 交易已上链移除


class TestChainValidation:
    def test_validate_chain_genesis_only(self):
        bc = Blockchain()
        assert bc.validate_chain() is True

    def test_validate_chain_after_append(self):
        bc = Blockchain()
        genesis = bc.latest_block
        bc.append_block(_make_block(genesis, []))
        bc.append_block(_make_block(bc.latest_block, []))
        assert bc.validate_chain() is True

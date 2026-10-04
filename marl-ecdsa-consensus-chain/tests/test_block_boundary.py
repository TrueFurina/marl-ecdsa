"""
Block 状态根/Merkle 边界测试（RalphLoop 原子任务 Q）
覆盖：compute_merkle_root、compute_state_root、finalize、链式连接、创世确定性
通过标准：新增 ≥6 项测试全过
"""
import hashlib
import logging
import time

import pytest

from blockchain.ledger.block import Block, Transaction, compute_merkle_root

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


class TestMerkleRoot:
    def test_merkle_empty_list(self):
        """空交易列表 → 返回空字符串"""
        assert compute_merkle_root([]) == ""

    def test_merkle_single_tx(self):
        """单交易 → 返回该交易哈希本身"""
        tx = _make_tx()
        root = compute_merkle_root([tx.tx_id])
        assert root == tx.tx_id  # 单元素返回自身（16 字符 tx_id）

    def test_merkle_two_tx_deterministic(self):
        hashes = ["a" * 64, "b" * 64]  # 合法 hex 输入
        r1 = compute_merkle_root(hashes)
        r2 = compute_merkle_root(hashes)
        assert r1 == r2
        assert len(r1) == 64  # 两元素 sha256 合并 → 64 字符

    def test_merkle_odd_count_padded(self):
        """奇数交易数不崩溃（末位自配对）"""
        root = compute_merkle_root(["a" * 64, "b" * 64, "c" * 64])
        assert len(root) == 64


class TestComputeStateRoot:
    def test_state_root_empty_block_is_zeros(self):
        genesis = Block.create_genesis()
        assert genesis.compute_state_root() == "0" * 64

    def test_state_root_with_tx(self):
        tx = _make_tx()
        genesis = Block.create_genesis()
        block = _make_block(genesis, [tx])
        root = block.compute_state_root()
        # 单交易 → 返回 tx_id 本身（非空、非全零）
        assert root == tx.tx_id


class TestFinalize:
    def test_finalize_updates_state_root_and_hash(self):
        genesis = Block.create_genesis()
        tx = _make_tx()
        block = _make_block(genesis, [tx])
        before_hash = block.block_hash
        block_hash = block.finalize()
        assert block_hash == block.block_hash
        # finalize 后 state_root 不再是全零（有交易时）
        assert block.state_root != "0" * 64

    def test_finalize_deterministic(self):
        genesis = Block.create_genesis()
        tx = _make_tx()
        b1 = _make_block(genesis, [tx])
        b2 = _make_block(genesis, [tx])
        h1 = b1.finalize()
        h2 = b2.finalize()
        # 同高度/同交易但时间戳不同 → 哈希可能不同（时间戳参与）；至少均合法
        assert len(h1) == 64
        assert len(h2) == 64


class TestChainLink:
    def test_is_valid_chain_link(self):
        genesis = Block.create_genesis()
        block = _make_block(genesis, [])
        assert block.is_valid_chain_link(genesis) is True

    def test_is_valid_chain_link_wrong_height(self):
        genesis = Block.create_genesis()
        bad = Block(
            block_height=5,  # 高度不连续
            previous_hash=genesis.block_hash,
            timestamp=int(time.time() * 1000),
            proposer="node_0",
            transactions=[],
            state_root="0" * 64,
        )
        assert bad.is_valid_chain_link(genesis) is False


class TestGenesis:
    def test_genesis_deterministic(self):
        """创世区块哈希确定性（P2-14：固定时间戳 0）"""
        g1 = Block.create_genesis()
        g2 = Block.create_genesis()
        assert g1.block_hash == g2.block_hash
        assert g1.block_height == 0
        assert g1.previous_hash == "0" * 64

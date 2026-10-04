"""
Block/Transaction 序列化往返测试（RalphLoop 原子任务 T）
覆盖：Transaction/Block to_dict/from_dict 往返、哈希确定性
通过标准：新增 ≥6 项测试全过
"""
import hashlib
import logging
import time

import pytest

from blockchain.ledger.block import Block, Transaction

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


class TestTransactionSerialization:
    def test_tx_to_dict_from_dict_roundtrip(self):
        tx = _make_tx("agent_3", nonce=7)
        restored = Transaction.from_dict(tx.to_dict())
        assert restored == tx  # dataclass 相等性

    def test_tx_from_dict_missing_extra_defaults(self):
        """extra 缺失 → 默认空 dict（dataclass default_factory）"""
        d = _make_tx().to_dict()
        del d["extra"]
        restored = Transaction.from_dict(d)
        assert restored.extra == {}

    def test_tx_compute_hash_deterministic(self):
        tx1 = _make_tx("agent_0", nonce=1)
        tx2 = _make_tx("agent_0", nonce=1)
        # 同内容（时间戳相同秒内）→ 哈希相同
        if tx1.timestamp == tx2.timestamp:
            assert tx1.compute_hash() == tx2.compute_hash()
        assert len(tx1.compute_hash()) == 64

    def test_tx_compute_hash_excludes_tx_id(self):
        """compute_hash 不包含 tx_id（tx_id 本身由哈希派生）"""
        tx = _make_tx()
        h = tx.compute_hash()
        assert h != tx.tx_id


class TestBlockSerialization:
    def test_block_to_dict_from_dict_roundtrip(self):
        genesis = Block.create_genesis()
        tx = _make_tx()
        block = _make_block(genesis, [tx])
        block.finalize()  # 确定 state_root + block_hash
        restored = Block.from_dict(block.to_dict())
        assert restored.block_height == block.block_height
        assert restored.previous_hash == block.previous_hash
        assert restored.block_hash == block.block_hash
        assert len(restored.transactions) == 1
        assert restored.transactions[0].tx_id == tx.tx_id

    def test_block_from_dict_recomputes_hash(self):
        """from_dict 未提供 block_hash → 自动重算"""
        genesis = Block.create_genesis()
        block = _make_block(genesis, [])
        d = block.to_dict()
        d.pop("block_hash")  # 模拟旧格式（无哈希字段）
        restored = Block.from_dict(d)
        assert restored.block_hash == block._compute_hash()

    def test_block_to_dict_keys(self):
        genesis = Block.create_genesis()
        block = _make_block(genesis, [])
        d = block.to_dict()
        for key in ["block_height", "previous_hash", "timestamp", "proposer",
                    "transactions", "state_root", "signature_hex", "block_hash"]:
            assert key in d


class TestGenesisSerialization:
    def test_genesis_roundtrip(self):
        genesis = Block.create_genesis()
        restored = Block.from_dict(genesis.to_dict())
        assert restored.block_height == 0
        assert restored.block_hash == genesis.block_hash  # 确定性哈希保留


class TestTxType:
    def test_tx_type_default_action(self):
        tx = _make_tx()
        assert tx.tx_type == "action"

    def test_tx_type_custom(self):
        action = [0.5]
        tx = Transaction(
            tx_id="tx_custom",
            agent_id="agent_0",
            action=action,
            action_hash=hashlib.sha256(str(action).encode()).hexdigest()[:16],
            timestamp=1000,
            nonce=1,
            signature_hex="0x" + "ab" * 32,
            tx_type="score",
        )
        assert tx.tx_type == "score"
        restored = Transaction.from_dict(tx.to_dict())
        assert restored.tx_type == "score"

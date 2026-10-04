"""
区块与交易数据结构测试
测试 Transaction / Block 创建、哈希计算、序列化
"""
import pytest
import hashlib
import json
import time


@pytest.mark.blockchain
class TestTransaction:
    """交易数据结构测试"""

    def test_create_transaction(self, sample_transaction):
        """创建交易成功"""
        assert sample_transaction.agent_id == "agent_0"
        assert sample_transaction.tx_type == "action"
        assert sample_transaction.nonce == 1
        assert sample_transaction.signature_hex == "a1b2c3d4"

    def test_transaction_hash_computation(self, sample_transaction):
        """交易哈希计算正确"""
        tx_hash = sample_transaction.compute_hash()
        assert tx_hash is not None
        assert len(tx_hash) == 64  # SHA-256 hex = 64 chars
        assert all(c in '0123456789abcdef' for c in tx_hash)

    def test_transaction_hash_deterministic(self, sample_transaction):
        """同一交易多次计算哈希结果一致"""
        h1 = sample_transaction.compute_hash()
        h2 = sample_transaction.compute_hash()
        assert h1 == h2

    def test_different_transactions_different_hash(self, sample_transaction):
        """不同交易产生不同哈希"""
        from blockchain.ledger.block import Transaction
        tx2 = Transaction(
            tx_id="",
            agent_id="agent_1",
            action={"move": "down"},
            action_hash=hashlib.sha256(b"other_action").hexdigest(),
            timestamp=2000000,
            nonce=2,
            signature_hex="e5f6g7h8",
            tx_type="action"
        )
        tx2.tx_id = tx2.compute_hash()

        assert sample_transaction.tx_id != tx2.tx_id

    def test_transaction_to_dict_and_back(self, sample_transaction):
        """Transaction 序列化往返一致"""
        from blockchain.ledger.block import Transaction
        d = sample_transaction.to_dict()
        assert isinstance(d, dict)
        assert d["agent_id"] == "agent_0"

        restored = Transaction.from_dict(d)
        assert restored.agent_id == sample_transaction.agent_id
        assert restored.nonce == sample_transaction.nonce

    def test_transaction_hash_excludes_tx_id(self, sample_transaction):
        """哈希计算不包含 tx_id 本身（避免循环依赖）"""
        old_id = sample_transaction.tx_id
        # 改变 tx_id 不应改变哈希
        sample_transaction.tx_id = "different_id"
        new_hash = sample_transaction.compute_hash()
        assert new_hash == old_id

    def test_transaction_types(self):
        """不同交易类型创建正确"""
        from blockchain.ledger.block import Transaction
        tx_types = ["action", "register", "score", "penalty"]
        for tx_type in tx_types:
            tx = Transaction(
                tx_id="",
                agent_id="agent_0",
                action={"test": True},
                action_hash="abc123",
                timestamp=1000000,
                nonce=1,
                signature_hex="sig",
                tx_type=tx_type
            )
            assert tx.tx_type == tx_type


@pytest.mark.blockchain
class TestBlock:
    """区块数据结构测试"""

    def test_create_genesis_block(self):
        """创建创世区块"""
        from blockchain.ledger.block import Block
        block = Block.create_genesis()
        assert block.block_height == 0
        assert block.previous_hash == "0" * 64
        assert len(block.block_hash) == 64

    def test_create_block_with_transactions(self, sample_transaction):
        """创建包含交易的区块（使用正确 API）"""
        from blockchain.ledger.block import Block
        txs = [sample_transaction]
        block = Block(
            block_height=1,
            previous_hash="a" * 64,
            timestamp=int(time.time() * 1000),
            proposer="node_0",
            transactions=txs,
            state_root="b" * 64
        )

        assert block.block_height == 1
        assert len(block.transactions) == 1
        assert block.proposer == "node_0"
        assert len(block.block_hash) == 64
        # block_hash 在 __post_init__ 中自动计算
        assert block.block_hash is not None

    def test_block_hash_depends_on_transactions(self):
        """交易变化导致区块哈希改变"""
        from blockchain.ledger.block import Block, Transaction

        tx1 = Transaction(
            tx_id="", agent_id="a", action={}, action_hash="h1",
            timestamp=1000000, nonce=1, signature_hex="s1"
        )
        tx1.tx_id = tx1.compute_hash()

        tx2 = Transaction(
            tx_id="", agent_id="b", action={}, action_hash="h2",
            timestamp=2000000, nonce=2, signature_hex="s2"
        )
        tx2.tx_id = tx2.compute_hash()

        block1 = Block(
            block_height=1, previous_hash="p" * 64,
            timestamp=int(time.time() * 1000), proposer="n0",
            transactions=[tx1], state_root="w" * 64
        )
        block2 = Block(
            block_height=1, previous_hash="p" * 64,
            timestamp=int(time.time() * 1000), proposer="n0",
            transactions=[tx2], state_root="w" * 64
        )

        assert block1.block_hash != block2.block_hash

    def test_block_hash_depends_on_previous_hash(self, sample_transaction):
        """前一区块哈希变化导致当前区块哈希改变"""
        from blockchain.ledger.block import Block
        t = int(time.time() * 1000)

        block1 = Block(
            block_height=1, previous_hash="a" * 64,
            timestamp=t, proposer="n0",
            transactions=[sample_transaction], state_root="w" * 64
        )
        block2 = Block(
            block_height=1, previous_hash="b" * 64,
            timestamp=t, proposer="n0",
            transactions=[sample_transaction], state_root="w" * 64
        )

        assert block1.block_hash != block2.block_hash

    def test_block_to_dict(self, sample_transaction):
        """Block 序列化为字典"""
        from blockchain.ledger.block import Block
        block = Block(
            block_height=1, previous_hash="p" * 64,
            timestamp=int(time.time() * 1000), proposer="n0",
            transactions=[sample_transaction], state_root="w" * 64
        )

        d = block.to_dict()
        assert isinstance(d, dict)
        assert d["block_height"] == 1
        assert d["proposer"] == "n0"
        assert "transactions" in d
        assert "block_hash" in d

    def test_multiple_transactions_in_block(self):
        """区块可包含多笔交易"""
        from blockchain.ledger.block import Block, Transaction

        txs = []
        for i in range(5):
            tx = Transaction(
                tx_id="", agent_id=f"agent_{i}", action={"idx": i},
                action_hash=f"h{i}", timestamp=1000000 + i, nonce=i,
                signature_hex=f"s{i}"
            )
            tx.tx_id = tx.compute_hash()
            txs.append(tx)

        block = Block(
            block_height=1, previous_hash="p" * 64,
            timestamp=int(time.time() * 1000), proposer="n0",
            transactions=txs, state_root="w" * 64
        )
        assert len(block.transactions) == 5

    def test_is_valid_chain_link(self):
        """链式连接验证"""
        from blockchain.ledger.block import Block

        genesis = Block.create_genesis()
        block1 = Block(
            block_height=1, previous_hash=genesis.block_hash,
            timestamp=1000, proposer="n0",
            transactions=[], state_root="s" * 64
        )

        assert block1.is_valid_chain_link(genesis) is True

    def test_is_valid_chain_link_wrong_height(self):
        """高度不连续时链式验证失败"""
        from blockchain.ledger.block import Block

        genesis = Block.create_genesis()
        block_wrong = Block(
            block_height=5, previous_hash=genesis.block_hash,
            timestamp=1000, proposer="n0",
            transactions=[], state_root="s" * 64
        )

        assert block_wrong.is_valid_chain_link(genesis) is False

    def test_is_valid_chain_link_wrong_prev_hash(self):
        """前一哈希不匹配时链式验证失败"""
        from blockchain.ledger.block import Block

        genesis = Block.create_genesis()
        block_wrong = Block(
            block_height=1, previous_hash="f" * 64,
            timestamp=1000, proposer="n0",
            transactions=[], state_root="s" * 64
        )

        assert block_wrong.is_valid_chain_link(genesis) is False

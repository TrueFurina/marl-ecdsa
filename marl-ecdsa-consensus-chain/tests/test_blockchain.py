"""
区块链链式完整性测试
测试区块添加、链式验证、不可篡改性
"""
import pytest
import time
import hashlib
import copy

from blockchain.ledger.block import Block, Transaction


def _make_block(prev_block, transactions, proposer="node_0"):
    """辅助函数：创建可追加的区块"""
    return Block(
        block_height=prev_block.block_height + 1,
        previous_hash=prev_block.block_hash,
        timestamp=int(time.time() * 1000),
        proposer=proposer,
        transactions=transactions,
        state_root="s" * 64
    )


@pytest.mark.blockchain
class TestBlockchainIntegrity:
    """区块链链式完整性测试"""

    def test_genesis_block_created(self, block_chain_instance):
        """创世区块自动创建"""
        bc = block_chain_instance
        assert bc.height == 0  # 创世区块高度为 0
        genesis = bc.get_block(0)
        assert genesis.block_height == 0
        assert genesis.previous_hash == "0" * 64
        assert genesis.block_hash is not None

    def test_validate_genesis_chain(self, block_chain_instance):
        """仅含创世区块的链通过验证"""
        bc = block_chain_instance
        assert bc.validate_chain() is True

    def test_append_block_maintains_chain(self, block_chain_instance, sample_transaction):
        """追加区块后链验证通过"""
        bc = block_chain_instance
        initial_height = bc.height

        block = _make_block(bc.latest_block, [sample_transaction])
        bc.append_block(block)

        assert bc.height == initial_height + 1
        assert bc.validate_chain() is True

    def test_chain_links_correctly(self, block_chain_instance, sample_transaction):
        """多个区块正确链接"""
        bc = block_chain_instance

        for i in range(1, 6):
            tx = copy.deepcopy(sample_transaction)
            tx.nonce = i
            tx.tx_id = tx.compute_hash()
            block = _make_block(bc.latest_block, [tx], proposer=f"node_{i % 3}")
            bc.append_block(block)

        assert bc.height == 5  # 0 genesis + 5 added
        assert bc.validate_chain() is True

        # 验证每个区块的 previous_hash 指向前一个区块的 block_hash
        for i in range(1, bc.height + 1):
            curr = bc.get_block(i)
            prev = bc.get_block(i - 1)
            assert curr.previous_hash == prev.block_hash

    def test_tampered_transaction_invalidates_chain(self, block_chain_instance, sample_transaction):
        """篡改交易 tx_id 后链验证失败（区块哈希依赖 tx_hashes）"""
        bc = block_chain_instance
        block = _make_block(bc.latest_block, [copy.deepcopy(sample_transaction)])
        bc.append_block(block)

        # 篡改交易 tx_id（区块哈希依赖 tx_hashes 列表）
        tampered_tx = bc.get_block(1).transactions[0]
        tampered_tx.tx_id = "tampered_tx_id_deadbeef"
        # 不更新 block_hash → _compute_hash() 将返回不同的哈希
        assert bc.validate_chain() is False

    def test_tampered_previous_hash_invalidates_chain(self, block_chain_instance, sample_transaction):
        """篡改 previous_hash 导致链验证失败"""
        bc = block_chain_instance

        tx1 = copy.deepcopy(sample_transaction)
        tx1.nonce = 1; tx1.tx_id = tx1.compute_hash()
        bc.append_block(_make_block(bc.latest_block, [tx1], proposer="n0"))

        tx2 = copy.deepcopy(sample_transaction)
        tx2.nonce = 2; tx2.tx_id = tx2.compute_hash()
        bc.append_block(_make_block(bc.latest_block, [tx2], proposer="n1"))

        # 直接修改内部 _chain 中第1个区块的 previous_hash
        bc._chain[1].previous_hash = "deadbeef" * 8
        assert bc.validate_chain() is False

    def test_invalid_block_hash_detected(self, block_chain_instance, sample_transaction):
        """直接篡改区块哈希被检测"""
        bc = block_chain_instance
        block = _make_block(bc.latest_block, [sample_transaction])
        bc.append_block(block)

        # 直接篡改区块哈希
        bc._chain[1].block_hash = "ffff" * 16  # 不匹配的哈希
        assert bc.validate_chain() is False

    def test_chain_after_multiple_blocks_passes(self, block_chain_instance, sample_transaction):
        """大量区块添加后仍然通过验证（压力/稳定性）"""
        bc = block_chain_instance

        for i in range(1, 51):
            tx = copy.deepcopy(sample_transaction)
            tx.nonce = i
            tx.tx_id = tx.compute_hash()
            block = _make_block(bc.latest_block, [tx], proposer=f"node_{i % 4}")
            bc.append_block(block)

        assert bc.height == 50
        assert bc.validate_chain() is True


@pytest.mark.blockchain
class TestBlockchainGetBlock:
    """区块查询测试"""

    def test_get_latest_block(self, block_chain_instance, sample_transaction):
        """获取最新区块"""
        bc = block_chain_instance
        block = _make_block(bc.latest_block, [sample_transaction])
        bc.append_block(block)

        latest = bc.latest_block
        assert latest is not None
        assert latest.block_height == 1

    def test_get_block_by_height(self, block_chain_instance, sample_transaction):
        """按高度获取区块"""
        bc = block_chain_instance

        tx1 = copy.deepcopy(sample_transaction)
        tx1.nonce = 1; tx1.tx_id = tx1.compute_hash()
        bc.append_block(_make_block(bc.latest_block, [tx1], proposer="n0"))

        tx2 = copy.deepcopy(sample_transaction)
        tx2.nonce = 2; tx2.tx_id = tx2.compute_hash()
        bc.append_block(_make_block(bc.latest_block, [tx2], proposer="n1"))

        block_0 = bc.get_block(0)
        block_1 = bc.get_block(1)
        block_2 = bc.get_block(2)

        assert block_0.block_height == 0
        assert block_1.block_height == 1
        assert block_2.block_height == 2

    def test_get_nonexistent_block(self, block_chain_instance):
        """查询不存在高度返回 None"""
        bc = block_chain_instance
        result = bc.get_block(999)
        assert result is None


@pytest.mark.blockchain
class TestBlockchainWorldState:
    """世界状态相关测试"""

    def test_state_root_field_exists(self, block_chain_instance, sample_transaction):
        """区块包含 state_root 字段"""
        bc = block_chain_instance
        root0 = bc.get_block(0).state_root
        assert root0 == "0" * 64  # 创世区块 state_root

        block = _make_block(bc.latest_block, [sample_transaction])
        bc.append_block(block)

        root1 = bc.get_block(1).state_root
        assert root1 is not None
        assert isinstance(root1, str)

    def test_state_root_independent_of_transactions(self, block_chain_instance, sample_transaction):
        """state_root 需显式设置（不由交易自动计算）"""
        bc = block_chain_instance
        block1 = _make_block(bc.latest_block, [sample_transaction])
        bc.append_block(block1)

        # state_root 由构造时传入的 "s"*64 决定，与交易无关
        assert bc.get_block(1).state_root == "s" * 64


@pytest.mark.blockchain
class TestBlockchainTxPool:
    """交易池测试"""

    def test_add_transaction_to_pool(self, block_chain_instance, sample_transaction):
        """交易可加入交易池"""
        bc = block_chain_instance
        result = bc.add_transaction(sample_transaction)
        assert result is True
        assert bc.get_tx_pool_size() >= 1

    def test_duplicate_transaction_rejected(self, block_chain_instance, sample_transaction):
        """重复交易被拒绝"""
        bc = block_chain_instance
        bc.add_transaction(sample_transaction)
        result = bc.add_transaction(sample_transaction)
        assert result is False

    def test_find_transaction(self, block_chain_instance, sample_transaction):
        """在链上查找交易"""
        bc = block_chain_instance
        block = _make_block(bc.latest_block, [sample_transaction])
        bc.append_block(block)

        found = bc.find_transaction(sample_transaction.tx_id)
        assert found is not None
        assert found.tx_id == sample_transaction.tx_id

    def test_find_nonexistent_transaction(self, block_chain_instance):
        """查找不存在的交易返回 None"""
        bc = block_chain_instance
        result = bc.find_transaction("nonexistent_tx_id")
        assert result is None

    def test_get_stats(self, block_chain_instance, sample_transaction):
        """统计信息接口正常"""
        bc = block_chain_instance
        block = _make_block(bc.latest_block, [sample_transaction])
        bc.append_block(block)

        stats = bc.get_stats()
        assert isinstance(stats, dict)
        assert stats["height"] == 1
        assert stats["total_blocks"] == 2
        assert stats["total_transactions"] >= 1

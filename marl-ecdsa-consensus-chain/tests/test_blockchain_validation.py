"""
Blockchain 区块验证边界测试（RalphLoop 原子任务 BB）
覆盖：链式/哈希验证、交易签名验证（无/有 identity_contract 双场景）
通过标准：新增 ≥6 项测试全过
"""
import hashlib
import logging
import time

import pytest

from blockchain.ledger.block import Block, Transaction
from blockchain.ledger.blockchain import Blockchain

logging.basicConfig(level=logging.CRITICAL)


def _make_tx(agent_id="agent_0", nonce=1, verified=True, sig=True, extra=None):
    action = [0.1, 0.2]
    return Transaction(
        tx_id=hashlib.sha256(f"{agent_id}{nonce}".encode()).hexdigest()[:16],
        agent_id=agent_id,
        action=action,
        action_hash=hashlib.sha256(str(action).encode()).hexdigest()[:16],
        timestamp=int(time.time() * 1000),
        nonce=nonce,
        signature_hex=("0x" + "ab" * 32) if sig else "",
        extra=extra if extra is not None else {'verified': verified, 'message_hex': '00'},
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


class TestChainValidation:
    def test_wrong_prev_hash_rejected(self):
        """链式验证失败：previous_hash 不匹配 → False"""
        bc = Blockchain()
        bad = Block(
            block_height=1, previous_hash="0" * 64,  # 错误前块哈希
            timestamp=int(time.time() * 1000), proposer="node_0",
            transactions=[], state_root="0" * 64,
        )
        assert bc._validate_new_block(bad) is False

    def test_tampered_hash_rejected(self):
        """哈希不匹配：block_hash 被篡改 → False"""
        bc = Blockchain()
        block = _make_block(bc.latest_block, [])
        block.block_hash = "0" * 64
        assert bc._validate_new_block(block) is False

    def test_valid_block_accepted(self):
        """合法区块 → True"""
        bc = Blockchain()
        block = _make_block(bc.latest_block, [])
        assert bc._validate_new_block(block) is True


class TestNoIdentityContract:
    """无 identity_contract（stub 模式）：空签名/未验证交易向后兼容允许"""

    def test_empty_signature_allowed(self):
        bc = Blockchain()  # 无 identity_contract
        tx = _make_tx(sig=False)
        block = _make_block(bc.latest_block, [tx])
        assert bc._validate_new_block(block) is True

    def test_unverified_tx_allowed(self):
        bc = Blockchain()
        tx = _make_tx(verified=False)
        block = _make_block(bc.latest_block, [tx])
        assert bc._validate_new_block(block) is True


class TestWithIdentityContract:
    """有 identity_contract：严格拒绝未验证/空签名交易"""

    def test_unverified_tx_rejected(self):
        class _FakeIdentity:
            def get_public_key(self, agent_id):
                return None  # 公钥未注册
        bc = Blockchain(identity_contract=_FakeIdentity())
        tx = _make_tx(verified=False)
        block = _make_block(bc.latest_block, [tx])
        assert bc._validate_new_block(block) is False

    def test_empty_signature_rejected(self):
        class _FakeIdentity:
            def get_public_key(self, agent_id):
                return None
        bc = Blockchain(identity_contract=_FakeIdentity())
        tx = _make_tx(sig=False)
        block = _make_block(bc.latest_block, [tx])
        assert bc._validate_new_block(block) is False

    def test_unregistered_pubkey_rejected(self):
        """有 identity_contract + 有签名但公钥未注册 → 拒绝"""
        class _FakeIdentity:
            def get_public_key(self, agent_id):
                return None  # 未注册
        bc = Blockchain(identity_contract=_FakeIdentity())
        tx = _make_tx(verified=True, sig=True)
        block = _make_block(bc.latest_block, [tx])
        assert bc._validate_new_block(block) is False

    def test_append_rejects_unverified(self):
        """append_block 级联：未验证交易 → 区块拒绝上链"""
        class _FakeIdentity:
            def get_public_key(self, agent_id):
                return None
        bc = Blockchain(identity_contract=_FakeIdentity())
        tx = _make_tx(verified=False)
        block = _make_block(bc.latest_block, [tx])
        assert bc.append_block(block) is False
        assert bc.height == 0  # 链未增长

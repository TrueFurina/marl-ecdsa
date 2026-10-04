"""
train.py 交易级 ECDSA 验签接线回归测试（2026-09-28 修复 P0-1）
覆盖：
  1. 正常模式 → Blockchain 注入 identity_contract（验签真实生效）
  2. 消融模式(ablate_security) → 不注入（保持既有消融实验行为可复现）
  3. 注入后：有效签名交易可上链（正控）
  4. 注入后：空签名交易被拒绝上链（强制生效）
  5. 注入后：签名被篡改的交易被拒绝上链（强制生效）

背景：此前 train.py 构造 `Blockchain()` 未传 identity_contract，导致
blockchain.py:_validate_new_block 整段 ECDSA 验签被 `if self._identity_contract is not None`
跳过——真实训练里验签只打日志不拦截。本测试锁死接线，防止再次被静默摘掉。
无磁盘副作用：KeyManager 以内存桩替换，不读写 ./keys。
"""
import logging

import pytest

import train as train_mod

logging.basicConfig(level=logging.CRITICAL)


def _pub_hex(priv):
    """SECP256R1 (P-256) 公钥 → 130 位十六进制非压缩点（与 ECDSAUtils.CURVE 一致）"""
    nums = priv.public_key().public_numbers()
    return "04" + f"{nums.x:064x}" + f"{nums.y:064x}"


class _StubKeyManager:
    """内存密钥管理桩：不落盘，生成合法公钥 hex"""

    def __init__(self, *a, **kw):
        self._keys = {}

    def generate_or_load(self, agent_id):
        from blockchain.crypto.ecdsa_utils import ECDSAUtils
        from cryptography.hazmat.primitives.asymmetric import ec
        if agent_id not in self._keys:
            self._keys[agent_id] = ec.generate_private_key(ECDSAUtils.CURVE)
        priv = self._keys[agent_id]
        return priv, priv.public_key()

    def get_public_key_hex(self, agent_id):
        priv = self._keys.get(agent_id)
        return _pub_hex(priv) if priv else None

    def get_public_key(self, agent_id):
        priv = self._keys.get(agent_id)
        return priv.public_key() if priv else None

    def get_private_key(self, agent_id):
        return self._keys.get(agent_id)


class _StubTrainer:
    """训练器桩：仅需可构造，避免测试强依赖 torch 与重量级初始化"""

    def __init__(self, *a, **kw):
        self.agents = [None, None, None]


@pytest.fixture
def wired(monkeypatch):
    """构造一个轻量 Trainer（KeyManager/训练器均以桩替换）"""
    monkeypatch.setattr(train_mod, "KeyManager", _StubKeyManager)
    monkeypatch.setattr(train_mod, "QMIXTrainer", _StubTrainer)

    def _build(**kw):
        cfg = train_mod.TrainingConfig(
            mode="bc_marl", n_agents=3, n_landmarks=3, max_steps=5, n_episodes=1,
            use_p2p=False, **kw,
        )
        return train_mod.MARLBlockchainTrainer(cfg)

    return _build


class TestIdentityContractWiring:
    def test_normal_mode_injects_identity_contract(self, wired):
        """正常模式：Blockchain 必须持有 identity_contract，否则验签被跳过"""
        t = wired(ablate_security=False)
        assert t.blockchain._identity_contract is not None
        # 必须是同一个对象（同一 WorldState 下的身份合约）
        assert t.blockchain._identity_contract is t.identity_contract

    def test_ablate_mode_does_not_inject(self, wired):
        """消融模式：不注入，保持既有消融实验（results/ablation、NR e4/e9）行为可复现"""
        t = wired(ablate_security=True)
        assert t.blockchain._identity_contract is None

    def test_agents_registered_so_verification_can_pass(self, wired):
        """接线生效的前提：所有 agent 公钥已注册，get_public_key 可查到"""
        t = wired(ablate_security=False)
        for aid in t.agent_ids:
            assert t.identity_contract.get_public_key(aid) is not None


class TestInjectedChainEnforcement:
    """证明注入后验签是「强制执行」而非「仅记录」"""

    @staticmethod
    def _signed_tx(agent_id, priv, ic):
        """构造一笔带真实 ECDSA 签名的交易"""
        from blockchain.crypto.ecdsa_utils import ECDSAUtils
        from blockchain.ledger.block import Transaction
        from blockchain.ledger.blockchain import Blockchain
        pkg = ECDSAUtils.sign_action(agent_id=agent_id, private_key=priv,
                                     action=[0.1, 0.2], nonce=1, timestamp=1000)
        tx = Transaction(
            tx_id="", agent_id=agent_id, action=[0.1, 0.2], action_hash="h",
            timestamp=1000, nonce=1, signature_hex=pkg["signature_hex"],
            tx_type="action",
            extra={"step": 0, "env_reward": 0.0, "verified": True,
                   "r": pkg["r"], "s": pkg["s"], "message_hex": pkg["message_hex"]},
        )
        tx.tx_id = tx.compute_hash()
        return tx

    def _chain_with_agent(self):
        from blockchain.contracts.identity_contract import IdentityContract
        from blockchain.crypto.ecdsa_utils import ECDSAUtils
        from blockchain.ledger.blockchain import Blockchain
        from blockchain.ledger.world_state import WorldState
        from cryptography.hazmat.primitives.asymmetric import ec
        ws = WorldState()
        ic = IdentityContract(ws)
        priv = ec.generate_private_key(ECDSAUtils.CURVE)
        ic.register("agent_0", ECDSAUtils.public_key_to_hex(priv.public_key()))
        return Blockchain(identity_contract=ic), ic, priv

    def test_valid_tx_accepted(self):
        """正控：真实签名的交易可上链"""
        from blockchain.ledger.block import Block
        bc, ic, priv = self._chain_with_agent()
        tx = self._signed_tx("agent_0", priv, ic)
        blk = Block(block_height=1, previous_hash=bc.latest_block.block_hash,
                    timestamp=1000, proposer="agent_0", transactions=[tx],
                    state_root="r", signature_hex="")
        assert bc.append_block(blk) is True
        assert bc.height == 1

    def test_unsigned_tx_rejected(self):
        """强制生效：空签名交易被拒绝"""
        from blockchain.ledger.block import Block, Transaction
        bc, ic, priv = self._chain_with_agent()
        tx = Transaction(tx_id="", agent_id="agent_0", action=[0.1], action_hash="h",
                         timestamp=1000, nonce=1, signature_hex="", tx_type="action",
                         extra={"step": 0, "env_reward": 0.0, "verified": True})
        tx.tx_id = tx.compute_hash()
        blk = Block(block_height=1, previous_hash=bc.latest_block.block_hash,
                    timestamp=1000, proposer="agent_0", transactions=[tx],
                    state_root="r", signature_hex="")
        assert bc.append_block(blk) is False
        assert bc.height == 0

    def test_tampered_signature_rejected(self):
        """强制生效：签名被篡改的交易被拒绝"""
        from blockchain.ledger.block import Block
        bc, ic, priv = self._chain_with_agent()
        tx = self._signed_tx("agent_0", priv, ic)
        # 篡改签名（保持 hex 合法、DER 结构可能失效）
        tx.signature_hex = "30" + tx.signature_hex[2:-4] + "beef"
        tx.tx_id = tx.compute_hash()
        blk = Block(block_height=1, previous_hash=bc.latest_block.block_hash,
                    timestamp=1000, proposer="agent_0", transactions=[tx],
                    state_root="r", signature_hex="")
        assert bc.append_block(blk) is False
        assert bc.height == 0

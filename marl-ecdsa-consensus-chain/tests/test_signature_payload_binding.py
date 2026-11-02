"""签名与载荷绑定回归锁（P0 安全修复 2026-11-02）

漏洞形态：`ECDSAUtils.verify_action_package` 原先只对 `package['message_hex']`
里的字节验签，而 `message_hex` 是交易自带字段。于是拿到某 agent 任意一条公开
历史签名（链上 `tx.extra['message_hex']` 就存着），就能把它贴到一笔完全不同的
交易上（换 action / timestamp / nonce），验签照样通过 —— 以该 agent 的名义
写入任意行为。

修复：package 若携带 agent_id/action/timestamp/nonce，则要求 message_hex 中
真正被签的内容与这些字段一致；不一致即拒绝。

本文件锁住四件事：
1. 正常签名包仍然通过（不误杀）；
2. 换 action 复用签名 → 拒绝（工具层 + 区块层双路径）；
3. 换 nonce / timestamp 复用签名 → 拒绝；
4. 旧式「只给 message_hex + signature_hex」的纯字节验签语义保持不变；
5. int / float 时间戳写法差异不被误判成篡改。
"""
import hashlib
import time

from blockchain.crypto.ecdsa_utils import ECDSAUtils
from blockchain.ledger.block import Block, Transaction
from blockchain.ledger.blockchain import Blockchain


class _FakeIdentity:
    """最小身份合约：固定返回同一把公钥（只验「签名对不对得上」）。"""

    def __init__(self, pub_hex: str):
        self._pub_hex = pub_hex

    def get_public_key(self, agent_id: str):
        return self._pub_hex


def _make_block(prev_block, transactions):
    return Block(
        block_height=prev_block.block_height + 1,
        previous_hash=prev_block.block_hash,
        timestamp=int(time.time() * 1000),
        proposer="node_0",
        transactions=transactions,
        state_root="0" * 64,
    )


def _forged_tx(legit_pkg, action, nonce=99999):
    """用受害者的合法签名包，伪造一笔 action 完全不同的交易。"""
    return Transaction(
        tx_id=hashlib.sha256(b"forged").hexdigest()[:16],
        agent_id=legit_pkg['agent_id'],
        action=action,
        action_hash=hashlib.sha256(str(action).encode()).hexdigest()[:16],
        timestamp=int(time.time() * 1000),
        nonce=nonce,
        signature_hex=legit_pkg['signature_hex'],   # 受害者对别的行为签的
        extra={
            'verified': True,
            'message_hex': legit_pkg['message_hex'],  # 受害者当时签的那条消息
            'r': legit_pkg['r'],
            's': legit_pkg['s'],
        },
    )


class TestLegitPackageStillVerifies:
    def test_sign_action_roundtrip(self):
        """正常签名包必须仍然通过（防止修复误杀）"""
        priv, pub = ECDSAUtils.generate_key_pair()
        pkg = ECDSAUtils.sign_action("agent_A", priv, {"type": "idle"}, nonce=1)
        assert ECDSAUtils.verify_action_package(pkg, pub) is True

    def test_float_timestamp_not_treated_as_tampering(self):
        """签名消息里是 int，调用方传 float（同值）不应被判篡改"""
        priv, pub = ECDSAUtils.generate_key_pair()
        pkg = ECDSAUtils.sign_action(
            "agent_A", priv, {"type": "idle"}, nonce=1, timestamp=1000
        )
        relaxed = dict(pkg)
        relaxed['timestamp'] = 1000.0
        assert ECDSAUtils.verify_action_package(relaxed, pub) is True

    def test_legacy_bytes_only_package_still_verifies(self):
        """只带 message_hex + signature_hex 的旧式调用保持纯字节验签语义"""
        priv, pub = ECDSAUtils.generate_key_pair()
        pkg = ECDSAUtils.sign_action("agent_A", priv, {"type": "idle"}, nonce=1)
        legacy = {
            'message_hex': pkg['message_hex'],
            'signature_hex': pkg['signature_hex'],
        }
        assert ECDSAUtils.verify_action_package(legacy, pub) is True


class TestForgedPayloadRejected:
    def test_reused_signature_with_new_action_rejected(self):
        """换 action 复用签名 → 工具层拒绝"""
        priv, pub = ECDSAUtils.generate_key_pair()
        legit = ECDSAUtils.sign_action("agent_A", priv, {"type": "idle"}, nonce=1)

        forged = {
            'agent_id': "agent_A",
            'action': {"type": "transfer", "amount": 999999},
            'timestamp': legit['timestamp'],
            'nonce': legit['nonce'],
            'message_hex': legit['message_hex'],
            'signature_hex': legit['signature_hex'],
        }
        assert ECDSAUtils.verify_action_package(forged, pub) is False

    def test_reused_signature_with_new_nonce_rejected(self):
        """换 nonce 复用签名 → 拒绝（防重放外的「签名解绑」）"""
        priv, pub = ECDSAUtils.generate_key_pair()
        legit = ECDSAUtils.sign_action("agent_A", priv, {"type": "idle"}, nonce=1)

        forged = dict(legit)
        forged['nonce'] = 99999
        assert ECDSAUtils.verify_action_package(forged, pub) is False

    def test_reused_signature_with_new_timestamp_rejected(self):
        """换 timestamp 复用签名 → 拒绝"""
        priv, pub = ECDSAUtils.generate_key_pair()
        legit = ECDSAUtils.sign_action("agent_A", priv, {"type": "idle"}, nonce=1)

        forged = dict(legit)
        forged['timestamp'] = legit['timestamp'] + 1
        assert ECDSAUtils.verify_action_package(forged, pub) is False

    def test_reused_signature_with_new_agent_id_rejected(self):
        """顶名（换 agent_id）复用签名 → 拒绝"""
        priv, pub = ECDSAUtils.generate_key_pair()
        legit = ECDSAUtils.sign_action("agent_A", priv, {"type": "idle"}, nonce=1)

        forged = dict(legit)
        forged['agent_id'] = "agent_B"
        assert ECDSAUtils.verify_action_package(forged, pub) is False


class TestBlockchainRejectsForgedTx:
    def test_block_with_forged_tx_rejected(self):
        """端到端：伪造交易不得通过 Blockchain._validate_new_block"""
        priv, pub = ECDSAUtils.generate_key_pair()
        pub_hex = ECDSAUtils.public_key_to_hex(pub)
        legit = ECDSAUtils.sign_action("agent_A", priv, {"type": "idle"}, nonce=1)

        bc = Blockchain(identity_contract=_FakeIdentity(pub_hex))
        block = _make_block(
            bc.latest_block,
            [_forged_tx(legit, {"type": "transfer", "amount": 999999})],
        )
        assert bc._validate_new_block(block) is False

    def test_block_with_genuine_tx_accepted(self):
        """端到端对照：真实签名的交易仍然可以上链（防止修复误杀）"""
        priv, pub = ECDSAUtils.generate_key_pair()
        pub_hex = ECDSAUtils.public_key_to_hex(pub)
        action = {"type": "idle"}
        legit = ECDSAUtils.sign_action("agent_A", priv, action, nonce=1)

        tx = Transaction(
            tx_id=hashlib.sha256(b"genuine").hexdigest()[:16],
            agent_id="agent_A",
            action=action,
            action_hash=hashlib.sha256(str(action).encode()).hexdigest()[:16],
            timestamp=legit['timestamp'],
            nonce=legit['nonce'],
            signature_hex=legit['signature_hex'],
            extra={
                'verified': True,
                'message_hex': legit['message_hex'],
                'r': legit['r'],
                's': legit['s'],
            },
        )
        bc = Blockchain(identity_contract=_FakeIdentity(pub_hex))
        assert bc._validate_new_block(_make_block(bc.latest_block, [tx])) is True

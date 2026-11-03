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
    """最小身份合约：固定返回同一把公钥（只验「签名对不对得上」）。

    `is_active` 是主链 2026-11-02 起（F05 封禁准入）会调用的方法：封禁身份不得
    上链。本测试不考封禁，恒返 True。
    """

    def __init__(self, pub_hex: str):
        self._pub_hex = pub_hex

    def get_public_key(self, agent_id: str):
        return self._pub_hex

    def is_active(self, agent_id: str) -> bool:
        return True


class _FakeKeyManager:
    """最小 KeyManager：只为出块者签名提供私钥（不涉及落盘/口令）。"""

    def __init__(self, private_key):
        self._priv = private_key

    def get_private_key(self, agent_id: str):
        return self._priv


def _make_block(prev_block, transactions, priv=None):
    """按**真实出块流程**造区块：构造 → finalize() → sign_block()。

    ⚠️ 2026-11-03 修正（CI 抓到，本机没抓到）：主链自 2026-11-02 起有区块级
    完整性校验 —— 出块者签名必须存在且可验证，`state_root` 必须等于对交易
    tx_id 重算的 Merkle 根。本测试原先是直接塞 `state_root="0" * 64` 且不签名
    的合成区块，在 CI 上报「区块 #1 缺少出块者签名，拒绝上链」。

    本机之所以是绿的：本地账本还是旧版（没有这道门）。**本地绿 ≠ CI 绿**，
    这条用例就是反例 —— 也说明把 CI 搬到仓库根是必要的。

    顺序不能反：`finalize()` 重算 state_root 与 block_hash，`sign_block()` 对
    `block_hash` 签名；签名不进哈希（见 `Block._compute_hash`），故可后签。
    """
    block = Block(
        block_height=prev_block.block_height + 1,
        previous_hash=prev_block.block_hash,
        timestamp=int(time.time() * 1000),
        proposer="node_0",
        transactions=transactions,
        state_root="0" * 64,
    )
    block.finalize()
    if priv is not None:
        block.sign_block(_FakeKeyManager(priv), agent_id="node_0")
    return block


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

    def test_bare_bytes_package_is_rejected(self):
        """只带 message_hex + signature_hex 的包 → **拒绝**（fail-closed）。

        ⚠️ 自我推翻（2026-11-03）：本文件初版此处断言"旧式纯字节包仍然通过"，
        并把它当成"不误杀"。那是错的 —— 一旦"缺 4 个字段就跳过绑定检查"，
        攻击者只要把 agent_id/action/timestamp/nonce 删掉，绑定检查就整段
        被跳过，验签退化成"这段字节确实被人签过"。而
        `cooperation_detector.filter_verified_packages()` 吃的正是**外部传入**
        的包（其 docstring 明写"含伪造/顶名包"），删字段即可绕过 = 后门。

        裸字节验签仍可用 `ECDSAUtils.verify(pub, message, signature)` 这个
        明确的底层入口；"签名包"语义下必须给全字段。
        """
        priv, pub = ECDSAUtils.generate_key_pair()
        pkg = ECDSAUtils.sign_action("agent_A", priv, {"type": "idle"}, nonce=1)
        legacy = {
            'message_hex': pkg['message_hex'],
            'signature_hex': pkg['signature_hex'],
        }
        assert ECDSAUtils.verify_action_package(legacy, pub) is False

    def test_missing_single_bound_field_rejected(self):
        """少任何一个承诺字段都必须拒绝（不能靠"少给字段"退出绑定）"""
        priv, pub = ECDSAUtils.generate_key_pair()
        pkg = ECDSAUtils.sign_action("agent_A", priv, {"type": "idle"}, nonce=1)
        for field in ('agent_id', 'action', 'timestamp', 'nonce'):
            partial = dict(pkg)
            partial.pop(field)
            assert ECDSAUtils.verify_action_package(partial, pub) is False, (
                f"缺 {field} 仍通过 —— 绑定检查可被「少给字段」绕过"
            )


class TestExtraIsBoundToo:
    """签名体里的额外键（extra）同样在绑定范围内。"""

    def test_undeclared_extra_key_rejected(self):
        """签名消息里有、package 未声明的键 → 拒绝"""
        priv, pub = ECDSAUtils.generate_key_pair()
        msg = ECDSAUtils.build_message(
            "agent_A", {"type": "idle"}, 1000, 1, extra={"role": "admin"}
        )
        pkg = {
            'agent_id': "agent_A",
            'action': {"type": "idle"},
            'timestamp': 1000,
            'nonce': 1,
            'message_hex': msg.hex(),
            'signature_hex': ECDSAUtils.sign(priv, msg).hex(),
        }
        assert ECDSAUtils.verify_action_package(pkg, pub) is False

    def test_declared_extra_key_is_accepted(self):
        """package 声明了同样的 extra → 通过（不误杀带附加字段的合法包）"""
        priv, pub = ECDSAUtils.generate_key_pair()
        msg = ECDSAUtils.build_message(
            "agent_A", {"type": "idle"}, 1000, 1, extra={"role": "admin"}
        )
        pkg = {
            'agent_id': "agent_A",
            'action': {"type": "idle"},
            'timestamp': 1000,
            'nonce': 1,
            'extra': {"role": "admin"},
            'message_hex': msg.hex(),
            'signature_hex': ECDSAUtils.sign(priv, msg).hex(),
        }
        assert ECDSAUtils.verify_action_package(pkg, pub) is True

    def test_tampered_extra_value_rejected(self):
        """extra 值被改 → 拒绝（否则附加字段是第二个不受保护的明文通道）"""
        priv, pub = ECDSAUtils.generate_key_pair()
        msg = ECDSAUtils.build_message(
            "agent_A", {"type": "idle"}, 1000, 1, extra={"role": "admin"}
        )
        pkg = {
            'agent_id': "agent_A",
            'action': {"type": "idle"},
            'timestamp': 1000,
            'nonce': 1,
            'extra': {"role": "guest"},
            'message_hex': msg.hex(),
            'signature_hex': ECDSAUtils.sign(priv, msg).hex(),
        }
        assert ECDSAUtils.verify_action_package(pkg, pub) is False


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
            priv,
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
        assert bc._validate_new_block(
            _make_block(bc.latest_block, [tx], priv)
        ) is True

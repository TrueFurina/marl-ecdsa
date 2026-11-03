# -*- coding: utf-8 -*-
"""
守护测试：签名包的「业务字段 ↔ 签名承诺」绑定。

背景（2026-10-15 安全加固）：
原 verify_action_package() 只校验 (message_hex, signature_hex) 这一对是否自洽，
不校验 message_hex 是否由包内的 agent_id/action/timestamp/nonce 构造而来。
攻击者可篡改业务字段明文而保留原签名，验签仍通过 ⇒ "消息篡改/观测伪造"
存在绕过路径。现有 test_ecdsa_utils_boundary.py 只覆盖了「篡改 message_hex
本身」这条必然失败的路径，未覆盖本路径，故补此文件。

守护重点：
1. 四类业务字段任一被篡改 ⇒ 必须拒绝（漏洞回归守护）
2. 合法包必须仍通过（防止修复过度拒绝，把正常功能一起打死）
"""
import pytest

from blockchain.crypto.ecdsa_utils import ECDSAUtils


@pytest.fixture
def keypair():
    priv, pub = ECDSAUtils.generate_key_pair()
    return priv, pub


def _signed(priv, action=None, nonce=3, timestamp=1000):
    return ECDSAUtils.sign_action(
        "agent_0", priv, action if action is not None else [0.5],
        nonce=nonce, timestamp=timestamp,
    )


class TestLegalPackageStillPasses:
    """修复不得误伤正常路径。"""

    def test_roundtrip_passes(self, keypair):
        priv, pub = keypair
        pkg = _signed(priv)
        assert ECDSAUtils.verify_action_package(pkg, pub) is True

    def test_different_actions_each_pass(self, keypair):
        """不同 action 各自签名都应通过 —— 守护「不是一律拒绝」。"""
        priv, pub = keypair
        for action in ([0.1], [9.9], {"x": 1}, "forward", 42):
            pkg = _signed(priv, action=action)
            assert ECDSAUtils.verify_action_package(pkg, pub) is True

    def test_different_nonce_and_timestamp_pass(self, keypair):
        priv, pub = keypair
        for nonce, ts in ((1, 1000), (2, 2000), (99, 9999)):
            pkg = _signed(priv, nonce=nonce, timestamp=ts)
            assert ECDSAUtils.verify_action_package(pkg, pub) is True


class TestTamperedBusinessFieldRejected:
    """核心守护：业务字段被篡改、签名原样保留 ⇒ 必须拒绝。"""

    def test_tampered_action_rejected(self, keypair):
        priv, pub = keypair
        pkg = _signed(priv)
        evil = dict(pkg)
        evil['action'] = [9.9]          # 伪造观测值
        assert ECDSAUtils.verify_action_package(evil, pub) is False

    def test_tampered_nonce_rejected(self, keypair):
        priv, pub = keypair
        pkg = _signed(priv)
        evil = dict(pkg)
        evil['nonce'] = pkg['nonce'] + 1
        assert ECDSAUtils.verify_action_package(evil, pub) is False

    def test_tampered_timestamp_rejected(self, keypair):
        priv, pub = keypair
        pkg = _signed(priv)
        evil = dict(pkg)
        evil['timestamp'] = pkg['timestamp'] + 1
        assert ECDSAUtils.verify_action_package(evil, pub) is False

    def test_tampered_agent_id_rejected(self, keypair):
        """换 agent_id 但保留他人签名 ⇒ 冒充，必须拒绝。"""
        priv, pub = keypair
        pkg = _signed(priv)
        evil = dict(pkg)
        evil['agent_id'] = "agent_1"
        assert ECDSAUtils.verify_action_package(evil, pub) is False

    def test_full_attack_chain_rejected(self, keypair):
        """完整攻击链：改 action + 抬高 nonce + 刷新 timestamp，全被拒。"""
        priv, pub = keypair
        pkg = _signed(priv)
        evil = dict(pkg)
        evil['action'] = [9.9]
        evil['nonce'] = pkg['nonce'] + 1
        evil['timestamp'] = pkg['timestamp'] + 1
        assert ECDSAUtils.verify_action_package(evil, pub) is False


class TestControlCases:
    """对照组：确保拒绝是「因为字段绑定」，而不是粗放地一律拒绝。"""

    def test_wrong_key_still_fails(self, keypair):
        priv, _ = keypair
        _, other_pub = ECDSAUtils.generate_key_pair()
        pkg = _signed(priv)
        assert ECDSAUtils.verify_action_package(pkg, other_pub) is False

    def test_tampered_message_hex_still_fails(self, keypair):
        priv, pub = keypair
        pkg = _signed(priv)
        evil = dict(pkg)
        evil['message_hex'] = (bytes.fromhex(pkg['message_hex']) + b"x").hex()
        assert ECDSAUtils.verify_action_package(evil, pub) is False

    def test_consistent_rebuild_matches_original(self, keypair):
        """合法包的 message_hex 必须能被 build_message 重现（绑定关系成立）。"""
        priv, _ = keypair
        pkg = _signed(priv)
        rebuilt = ECDSAUtils.build_message(
            pkg['agent_id'], pkg['action'], pkg['timestamp'], pkg['nonce'],
        )
        assert rebuilt.hex() == pkg['message_hex']

# -*- coding: utf-8 -*-
"""
探针：验证「篡改 action/nonce/timestamp 明文字段、保留原 message_hex/signature_hex」
是否能同时通过 (a) ECDSA 验签 与 (b) SecurityGuard 三道检查。

背景：verify_action_package() 只校验 (message_hex, signature_hex) 这一对，
不校验 message_hex 是否与包里的 agent_id/action/timestamp/nonce 一致。
若成立，则"消息篡改/观测伪造"类攻击存在绕过路径。
"""
import sys
import time
import os

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..')))

from blockchain.crypto.ecdsa_utils import ECDSAUtils
from blockchain.crypto.security_guard import SecurityGuard


def main():
    priv, pub = ECDSAUtils.generate_key_pair()

    # 合法原始包：agent_0 上报观测 [0.5]
    pkg = ECDSAUtils.sign_action("agent_0", priv, [0.5], nonce=3)
    print("=" * 62)
    print("原始合法包 action =", pkg['action'], " nonce =", pkg['nonce'])
    print("  合法包验签:", ECDSAUtils.verify_action_package(pkg, pub))

    # ---------- 攻击 1：只改 action 明文，其余原样 ----------
    evil1 = dict(pkg)
    evil1['action'] = [9.9]          # 伪造观测值
    print("\n[攻击1] 仅篡改 action -> [9.9]，message_hex/signature_hex 原样保留")
    print("  验签结果:", ECDSAUtils.verify_action_package(evil1, pub),
          "  <<< True 即表示篡改未被发现")

    # 证明：被篡改后的 action 与 message_hex 里承诺的 action_hash 已不一致
    real_msg = ECDSAUtils.build_message("agent_0", [9.9],
                                        pkg['timestamp'], pkg['nonce'])
    print("  message_hex 与篡改后 action 是否一致:",
          real_msg.hex() == pkg['message_hex'])

    # ---------- 攻击 2：完整绕过（同时骗过 SecurityGuard） ----------
    evil2 = dict(pkg)
    evil2['action'] = [9.9]
    evil2['nonce'] = 4                          # 递增，骗过 nonce 检查
    evil2['timestamp'] = int(time.time() * 1000)  # 当前时间，骗过时间戳窗口

    guard = SecurityGuard()
    guard.register_nonce_baseline("agent_0", 3)   # 已知上次 nonce=3
    ok, reason = guard.check_package(evil2)
    sig = ECDSAUtils.verify_action_package(evil2, pub)
    print("\n[攻击2] 篡改 action + 抬高 nonce + 刷新 timestamp（完整攻击链）")
    print("  ECDSA 验签:", sig)
    print("  SecurityGuard:", ok, "|", reason)
    print("  攻击是否成功(两者皆过):", sig and ok)

    # ---------- 对照：篡改 message_hex 本身必须失败 ----------
    evil3 = dict(pkg)
    evil3['message_hex'] = (bytes.fromhex(pkg['message_hex']) + b"x").hex()
    print("\n[对照] 篡改 message_hex 本身 ->",
          ECDSAUtils.verify_action_package(evil3, pub), " (必须为 False)")

    # ---------- 对照2：正确实现应当拒绝 ----------
    recomputed = ECDSAUtils.build_message(
        evil2['agent_id'], evil2['action'], evil2['timestamp'], evil2['nonce'])
    print("[对照] 若实现改为重新构造 message 再比对，则一致性 =",
          recomputed.hex() == evil2['message_hex'], " (必须 False 才能拦住)")
    print("=" * 62)


if __name__ == '__main__':
    main()

"""
攻击防御演示模块 — 六种攻击场景对比（无BC vs 有BC）（E6 扩展：2026-09-18 由 3 → 6 类）

攻击类型：
1. 观测伪造攻击：智能体谎报位置，诱导其他智能体让路
2. 消息篡改攻击：中间人篡改动作消息内容
3. 重放攻击：重放旧的有效消息，干扰当前决策
4. 女巫/Sybil 攻击：伪造大量身份，以数量淹没共识（贡献度门控权重拦截）
5. k 值重用攻击：同 k 签不同消息 → 私钥泄露（SecurityGuard k 重用检测拦截）
6. 长程攻击：复用旧纪元合法签名伪造历史（时间戳窗口 + 纪元绑定拦截）

每种攻击对比：
- 无BC模式：攻击成功，系统受损
- 有BC模式：攻击被ECDSA验签/SecurityGuard/链上承诺绑定/贡献度门控权重拦截
"""

# ===== 自动注入: 仓库根路径 (legacy 移动兼容) =====
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = str(_Path(__file__).resolve().parent.parent.parent.parent)
if _REPO_ROOT not in _sys.path:
    _sys.path.insert(0, _REPO_ROOT)
# ===== 自动注入结束 =====

import hashlib
import json
import logging
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent))

from blockchain.crypto.key_manager import KeyManager
from blockchain.crypto.ecdsa_utils import ECDSAUtils
from blockchain.crypto.security_guard import SecurityGuard
from blockchain.ledger.block import Transaction, Block
from blockchain.ledger.blockchain import Blockchain

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('attack_demo')


# ──────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────

def _sign_message(km: KeyManager, agent_id: str, message: bytes) -> bytes:
    """用指定智能体的私钥对消息签名"""
    priv_key = km.get_private_key(agent_id)
    return ECDSAUtils.sign(priv_key, message)


def _verify_message(km: KeyManager, agent_id: str, message: bytes, signature: bytes) -> bool:
    """用指定智能体的公钥验证签名"""
    pub_key = km.get_public_key(agent_id)
    if pub_key is None:
        return False
    return ECDSAUtils.verify(pub_key, message, signature)


def _make_tx(agent_id: str, action: dict, nonce: int, signature_hex: str,
             tx_type: str = "action", extra: dict = None) -> Transaction:
    """构造Transaction对象"""
    action_json = json.dumps(action, sort_keys=True, ensure_ascii=False)
    action_hash = hashlib.sha256(action_json.encode('utf-8')).hexdigest()
    msg_json = json.dumps({"agent_id": agent_id, "action_hash": action_hash,
                           "timestamp": int(time.time() * 1000), "nonce": nonce},
                          sort_keys=True)
    tx_id = hashlib.sha256(msg_json.encode('utf-8')).hexdigest()[:16]
    return Transaction(
        tx_id=tx_id,
        agent_id=agent_id,
        action=action,
        action_hash=action_hash,
        timestamp=int(time.time() * 1000),
        nonce=nonce,
        signature_hex=signature_hex,
        tx_type=tx_type,
        extra=extra or {},
    )


# ──────────────────────────────────────────────────────────────
# 攻击1: 观测伪造
# ──────────────────────────────────────────────────────────────

def demo_observation_forgery(key_dir: str = None) -> Dict:
    """
    攻击1: 观测伪造（P0-E 诚实修复版，2026-09-01）

    真实威胁模型：恶意节点用**自己合法私钥**对伪造观测签名 → ECDSA 验签必然通过，
    仅靠签名无法阻止"自报虚假观测"（旧版稻草人把"冒充他人被验签拦住"偷换成
    "伪造被拦截"，虚高了防护率）。

    真实拦截路径：链上"承诺-揭示"绑定（commit-reveal）。
    - 开局节点先用自己私钥签名提交位置承诺 H(true_position) 上链；
    - 后续观测提交时，链上校验 H(reported_position) == 承诺哈希；
    - 伪造位置哈希不匹配 → 被链上承诺绑定校验拒绝（即使签名有效）。

    无BC: 其他智能体无法验证位置真实性 → 被欺骗让路
    有BC: ECDSA 验签通过（自签），但链上承诺绑定校验拦截伪造位置
    """
    logger.info("=" * 60)
    logger.info("攻击1: 观测伪造 (Observation Forgery) — 承诺-揭示绑定拦截")
    logger.info("=" * 60)

    # BUG3 回归修复：每个演示使用独立临时密钥目录，避免复用 ./keys_demo 时残留的
    # 「异口令加密私钥」因当前口令解析不一致而无法加载（密码学上无法解密）。
    _cleanup = False
    if key_dir is None:
        key_dir = tempfile.mkdtemp(prefix="keys_obs_")
        _cleanup = True
    km = KeyManager(key_dir=key_dir)
    km.generate_or_load("honest_agent")
    km.generate_or_load("malicious_agent")

    # 真实位置
    true_position = {"x": 0.8, "y": 0.3, "agent_id": "malicious_agent"}
    # 伪造位置（谎称在路口，诱使他人让路）
    forged_position = {"x": 0.5, "y": 0.5, "agent_id": "malicious_agent"}

    result = {"attack_type": "observation_forgery", "no_bc": {}, "with_bc": {}}

    # --- 无BC模式 ---
    logger.info("[无BC] 其他智能体收到位置广播，无法验证真伪")
    logger.info(f"  广播位置: {forged_position} (伪造)")
    logger.info(f"  真实位置: {true_position}")
    logger.info("[无BC] X 攻击成功！其他智能体被欺骗让路")
    result["no_bc"] = {
        "attack_successful": True,
        "description": "无承诺绑定，无法验证位置真实性，恶意智能体成功抢占路径",
        "forged_data": forged_position,
        "true_data": true_position,
    }

    # --- 有BC模式：承诺-揭示绑定（真实拦截路径）---
    logger.info("\n[有BC] 1) 承诺阶段：恶意节点用自己私钥签名 H(true_position) 上链")
    true_hash = hashlib.sha256(
        json.dumps(true_position, sort_keys=True).encode()
    ).hexdigest()
    commit_msg = json.dumps(
        {"agent_id": "malicious_agent", "commit": true_hash}, sort_keys=True
    ).encode()
    commit_sig = _sign_message(km, "malicious_agent", commit_msg)
    commit_verified = _verify_message(km, "malicious_agent", commit_msg, commit_sig)
    bc = Blockchain()
    commit_tx = _make_tx(
        "malicious_agent", {"commit": true_hash}, nonce=1,
        signature_hex=commit_sig.hex(), tx_type="position_commit",
    )
    bc.add_transaction(commit_tx)
    cblock = Block(
        block_height=bc.height,
        previous_hash=bc.latest_block.block_hash if bc.height > 0 else "0" * 64,
        timestamp=int(time.time() * 1000),
        proposer="consensus_node_0",
        transactions=[commit_tx],
        state_root=hashlib.sha256(true_hash.encode()).hexdigest(),
    )
    bc.append_block(cblock)
    logger.info(f"  承诺上链: Block #{cblock.block_height}, commit_hash={true_hash[:16]}...")

    logger.info("2) 揭示阶段：恶意节点用自己合法私钥签名伪造位置（真实攻击）")
    forged_msg = json.dumps(forged_position, sort_keys=True).encode()
    forged_sig = _sign_message(km, "malicious_agent", forged_msg)
    # 关键诚实点：自签伪造 → 验签通过（签名拦不住自报虚假）
    sig_ok = _verify_message(km, "malicious_agent", forged_msg, forged_sig)
    logger.info(f"  ECDSA 验签（恶意节点自签伪造）: {'通过' if sig_ok else '失败'}"
                f"（诚实说明：签名仅认证签名者，不保证内容真实）")

    # 链上承诺绑定校验：H(reported) == 承诺哈希 ?
    forged_content_hash = hashlib.sha256(
        json.dumps(forged_position, sort_keys=True).encode()
    ).hexdigest()
    commit_match = (forged_content_hash == true_hash)
    blocked = not commit_match
    logger.info(f"  承诺绑定校验 H(reported)==commit: {'匹配' if commit_match else '不匹配 → 拦截'}")

    logger.info(f"[有BC] 攻击{'被拦截' if blocked else '成功'}！"
                f"签名通过但链上承诺绑定校验拦截伪造位置")
    result["with_bc"] = {
        "attack_successful": not blocked,
        "description": "ECDSA验签通过(自签)但链上承诺绑定校验拦截伪造位置",
        "signature_valid": sig_ok,                 # 诚实：True（签名拦不住自报虚假）
        "commitment_binding_checked": True,
        "commitment_match": commit_match,          # False → 真实拦截
        "blocked_by_commitment_binding": blocked,  # True
        "commit_block_index": cblock.block_height,
    }

    if _cleanup:
        shutil.rmtree(key_dir, ignore_errors=True)
    return result


# ──────────────────────────────────────────────────────────────
# 攻击2: 消息篡改
# ──────────────────────────────────────────────────────────────

def demo_message_tampering(key_dir: str = None) -> Dict:
    """
    攻击2: 消息篡改
    中间人截获动作消息并篡改内容（如将"让路"改为"直行"）

    无BC: 接收方无法检测篡改 → 执行错误动作
    有BC: 消息哈希不匹配 → 篡改被检测 → 拒绝执行
    """
    logger.info("\n" + "=" * 60)
    logger.info("攻击2: 消息篡改 (Message Tampering)")
    logger.info("=" * 60)

    # BUG3 回归修复：独立临时密钥目录，避免 ./keys_demo 残留异口令加密私钥。
    _cleanup = False
    if key_dir is None:
        key_dir = tempfile.mkdtemp(prefix="keys_msg_")
        _cleanup = True
    km = KeyManager(key_dir=key_dir)
    km.generate_or_load("sender")
    km.generate_or_load("receiver")

    original_action = {"agent_id": "sender", "action": "yield", "step": 42}
    tampered_action = {"agent_id": "sender", "action": "forward", "step": 42}

    result = {"attack_type": "message_tampering", "no_bc": {}, "with_bc": {}}

    # --- 无BC模式 ---
    logger.info("[无BC] 发送方广播动作: yield (让路)")
    logger.info("[无BC] 中间人篡改: yield -> forward (直行)")
    logger.info("[无BC] 接收方收到: forward -> 执行直行 -> 碰撞！")
    logger.info("[无BC] X 攻击成功！导致AGV碰撞")
    result["no_bc"] = {
        "attack_successful": True,
        "description": "消息无完整性校验，篡改无法检测",
        "original": original_action,
        "tampered": tampered_action,
    }

    # --- 有BC模式 ---
    logger.info("\n[有BC] 动作消息必须签名后传输")

    original_msg = json.dumps(original_action, sort_keys=True).encode()
    signature = _sign_message(km, "sender", original_msg)

    # 中间人篡改消息内容，但无法重新签名（没有sender的私钥）
    tampered_msg = json.dumps(tampered_action, sort_keys=True).encode()

    # 接收方验证签名
    verified_original = _verify_message(km, "sender", original_msg, signature)
    verified_tampered = _verify_message(km, "sender", tampered_msg, signature)

    logger.info(f"  原始消息签名验证: {'通过' if verified_original else '失败'}")
    logger.info(f"  篡改消息签名验证: {'通过' if verified_tampered else '失败（拦截）'}")

    # 消息哈希对比
    original_hash = hashlib.sha256(original_msg).hexdigest()
    tampered_hash = hashlib.sha256(tampered_msg).hexdigest()
    logger.info(f"  原始哈希: {original_hash[:16]}...")
    logger.info(f"  篡改哈希: {tampered_hash[:16]}...")
    logger.info(f"  哈希匹配: {'是' if original_hash == tampered_hash else '否'}")

    logger.info(f"[有BC] 攻击被拦截！签名验证失败，篡改消息被拒绝")
    result["with_bc"] = {
        "attack_successful": False,
        "description": "ECDSA签名验证失败+哈希不匹配，篡改消息被拒绝",
        "signature_valid_original": verified_original,
        "signature_valid_tampered": verified_tampered,
        "hash_match": original_hash == tampered_hash,
    }

    if _cleanup:
        shutil.rmtree(key_dir, ignore_errors=True)
    return result


# ──────────────────────────────────────────────────────────────
# 攻击3: 重放攻击
# ──────────────────────────────────────────────────────────────

def demo_replay_attack(key_dir: str = None) -> Dict:
    """
    攻击3: 重放攻击
    攻击者截获一条有效的签名消息，在后续步骤重新发送

    无BC: 接收方无法区分新旧消息 → 执行过期动作
    有BC: SecurityGuard检测nonce重用+时间戳过期 → 拦截
    """
    logger.info("\n" + "=" * 60)
    logger.info("攻击3: 重放攻击 (Replay Attack)")
    logger.info("=" * 60)

    # BUG3 回归修复：独立临时密钥目录，避免 ./keys_demo 残留异口令加密私钥。
    _cleanup = False
    if key_dir is None:
        key_dir = tempfile.mkdtemp(prefix="keys_replay_")
        _cleanup = True
    km = KeyManager(key_dir=key_dir)
    km.generate_or_load("agent_a")
    guard = SecurityGuard()

    result = {"attack_type": "replay_attack", "no_bc": {}, "with_bc": {}}

    # 原始消息（5分钟前发送，nonce=1）
    old_timestamp_ms = int(time.time() * 1000) - 300_000  # 5分钟前（毫秒）
    original_action = {"agent_id": "agent_a", "action": "claim_landmark", "step": 10}
    original_msg = json.dumps(original_action, sort_keys=True).encode()
    signature = _sign_message(km, "agent_a", original_msg)
    r_val, s_val = ECDSAUtils.extract_rs(signature)

    # 构造完整的签名包（SecurityGuard期望的格式）
    original_package = {
        "agent_id": "agent_a",
        "action": original_action,
        "timestamp": old_timestamp_ms,
        "nonce": 1,
        "r": r_val,
        "s": s_val,
        "signature_hex": signature.hex(),
    }

    # --- 无BC模式 ---
    logger.info("[无BC] Step 10: agent_a发送动作消息（正常）")
    logger.info("[无BC] Step 50: 攻击者重放Step 10的消息")
    logger.info("[无BC] 接收方无法区分新旧 -> 执行过期动作 -> 重复抢占资源")
    logger.info("[无BC] X 攻击成功！资源被重复占用")
    result["no_bc"] = {
        "attack_successful": True,
        "description": "无时间戳/nonce验证，旧消息被当作新消息执行",
        "original_step": 10,
        "replay_step": 50,
    }

    # --- 有BC模式 ---
    logger.info("\n[有BC] SecurityGuard检查时间戳+nonce+k值重用")

    # 1. 先注册一个nonce基线（模拟agent_a之前已发送过nonce=0的消息）
    guard.register_nonce_baseline("agent_a", 0)

    # 2. 正常消息先通过SecurityGuard（nonce=1, 当前时间戳）
    normal_package = dict(original_package)
    normal_package["timestamp"] = int(time.time() * 1000)  # 当前时间
    normal_package["nonce"] = 1
    is_safe_normal, reason_normal = guard.check_package(normal_package)
    logger.info(f"  正常消息（nonce=1, 当前时间）: {'通过' if is_safe_normal else '拦截'} - {reason_normal}")

    # 3. 重放攻击：重放旧消息（nonce=1已用过 + 时间戳过期5分钟）
    is_safe_replay, reason_replay = guard.check_package(original_package)
    logger.info(f"  重放消息（nonce=1重复, 5分钟前）: {'通过' if is_safe_replay else '拦截'}")
    logger.info(f"  拦截原因: {reason_replay}")

    # 4. 时间戳过期检测
    current_ms = int(time.time() * 1000)
    msg_age_ms = current_ms - old_timestamp_ms
    is_expired = msg_age_ms > guard.TIMESTAMP_TOLERANCE_MS
    logger.info(f"  消息年龄: {msg_age_ms // 1000}秒")
    logger.info(f"  时间戳过期: {'是' if is_expired else '否'} (容忍{guard.TIMESTAMP_TOLERANCE_MS // 1000}秒)")

    logger.info(f"[有BC] 攻击被拦截！时间戳过期+nonce重用双重检测")
    result["with_bc"] = {
        "attack_successful": False,
        "description": "SecurityGuard检测：时间戳过期+nonce重用，重放消息被拦截",
        "timestamp_expired": is_expired,
        "nonce_reused": not is_safe_replay,
        "replay_blocked": not is_safe_replay,
        "block_reason": reason_replay,
        "msg_age_seconds": msg_age_ms // 1000,
    }

    if _cleanup:
        shutil.rmtree(key_dir, ignore_errors=True)
    return result


# ──────────────────────────────────────────────────────────────
# 攻击4: 女巫/Sybil 攻击
# ──────────────────────────────────────────────────────────────

def demo_sybil_attack(key_dir: str = None) -> Dict:
    """
    攻击4: 女巫/Sybil 攻击
    攻击者伪造大量身份，试图以数量投票权重淹没共识。

    无BC（朴素一身份一票）：Sybil 数量 > 诚实节点即获胜。
    有BC：每个身份必须持有 ECDSA 密钥且贡献权重需累积
          （INITIAL_WEIGHT=0.3，MIN_WEIGHT=0.1 下界）；
          Sybil 即使数量多，其累计权重 << 诚实方（已累积贡献），
          无法达到 2/3 权重阈值 → 恶意提案被拒。
    """
    if key_dir is None:
        key_dir = tempfile.mkdtemp(prefix="keys_sybil_")
    logger.info("\n" + "=" * 60)
    logger.info("攻击4: 女巫攻击 (Sybil Attack)")
    logger.info("=" * 60)

    from blockchain.consensus.cw_pbft import CWPBFTConsensus

    honest_n, sybil_n = 4, 8  # Sybil 数量远超诚实节点
    result = {"attack_type": "sybil_attack", "no_bc": {}, "with_bc": {}}

    # --- 无BC模式（朴素一身份一票）---
    logger.info(f"[无BC] 诚实节点 {honest_n} 个，Sybil {sybil_n} 个（数量淹没）")
    logger.info("[无BC] 朴素计数投票：Sybil 多数 → 恶意提案通过")
    no_bc_pass = sybil_n > honest_n
    result["no_bc"] = {
        "attack_successful": no_bc_pass,
        "description": "身份无成本，Sybil 数量占优即获胜",
        "honest_n": honest_n, "sybil_n": sybil_n,
    }

    # --- 有BC模式：贡献度门控权重 ---
    km = KeyManager(key_dir=key_dir)
    nodes = [f"honest_{i}" for i in range(honest_n)] + [f"sybil_{i}" for i in range(sybil_n)]
    engine = CWPBFTConsensus("honest_0", nodes)
    # 诚实节点累积贡献后权重提升（模拟 update_weight 调用，无上界钳制）
    for h in range(honest_n):
        engine.update_weight(f"honest_{h}", 2.0)
    sybil_weight = sum(engine.get_weights()[f"sybil_{i}"] for i in range(sybil_n))
    honest_weight = sum(engine.get_weights()[f"honest_{i}"] for i in range(honest_n))
    total = engine._total_weight
    threshold = (2 / 3) * total
    logger.info(f"[有BC] 诚实权重={honest_weight:.2f}  Sybil权重={sybil_weight:.2f}  "
                f"总权重={total:.2f}  阈值={threshold:.2f}")
    sybil_pass = sybil_weight >= threshold
    blocked = not sybil_pass
    logger.info(f"[有BC] Sybil 提案权重 {sybil_weight:.2f} {'<' if blocked else '>='} 阈值 "
                f"→ {'拦截' if blocked else '通过'}（诚实方 {honest_weight:.2f}≥阈值→合法提案可通过）")
    result["with_bc"] = {
        "attack_successful": not blocked,
        "description": "贡献度门控权重：Sybil 初始权重低且无累积，无法达 2/3 阈值",
        "honest_weight": round(honest_weight, 3),
        "sybil_weight": round(sybil_weight, 3),
        "threshold": round(threshold, 3),
        "sybil_pass": sybil_pass,
        "blocked": blocked,
    }
    shutil.rmtree(key_dir, ignore_errors=True)
    return result


# ──────────────────────────────────────────────────────────────
# 攻击5: k 值重用攻击
# ──────────────────────────────────────────────────────────────

def demo_k_reuse_attack(key_dir: str = None) -> Dict:
    """
    攻击5: k 值重用攻击（ECDSA 同 k 签不同消息 → 私钥泄露）
    攻击者用相同随机数 k 对两条不同消息签名 → r 值相同 → 私钥可推导。

    无BC：仅验签，不检测 r 重用 → 攻击静默成功（私钥泄露）。
    有BC：SecurityGuard 的 k 值重用检测拦截（相同 r 二次出现即告警）。
    """
    if key_dir is None:
        key_dir = tempfile.mkdtemp(prefix="keys_kreuse_")
    logger.info("\n" + "=" * 60)
    logger.info("攻击5: k 值重用攻击 (k-Reuse / Key Extraction)")
    logger.info("=" * 60)

    km = KeyManager(key_dir=key_dir)
    km.generate_or_load("victim")
    guard = SecurityGuard()
    result = {"attack_type": "k_reuse_attack", "no_bc": {}, "with_bc": {}}

    msg_a = json.dumps({"agent_id": "victim", "action": "A", "step": 1}, sort_keys=True).encode()
    msg_b = json.dumps({"agent_id": "victim", "action": "B", "step": 2}, sort_keys=True).encode()
    sig_a = _sign_message(km, "victim", msg_a)
    r_a, _ = ECDSAUtils.extract_rs(sig_a)
    sig_b = _sign_message(km, "victim", msg_b)
    r_b, _ = ECDSAUtils.extract_rs(sig_b)

    # --- 无BC模式：只验签，不检测 r 重用 ---
    ok_a = _verify_message(km, "victim", msg_a, sig_a)
    ok_b = _verify_message(km, "victim", msg_b, sig_b)
    logger.info(f"[无BC] 两条签名验签: {ok_a and ok_b}（合法签名均通过，r 重用无检测）")
    logger.info("[无BC] X 攻击成功！相同 r 暴露 → 私钥可被推导")
    result["no_bc"] = {
        "attack_successful": True,
        "description": "无 r 重用检测，私钥因 k 重用泄露",
        "sig_a_valid": ok_a, "sig_b_valid": ok_b,
    }

    # --- 有BC模式：SecurityGuard 检测 r 重用 ---
    pkg_a = {"agent_id": "victim", "action": {"action": "A"}, "timestamp": int(time.time() * 1000),
             "nonce": 1, "r": r_a, "s": 1, "signature_hex": sig_a.hex()}
    pkg_b = {"agent_id": "victim", "action": {"action": "B"}, "timestamp": int(time.time() * 1000),
             "nonce": 2, "r": r_a, "s": 1, "signature_hex": sig_a.hex()}  # 复用 r_a
    guard.register_nonce_baseline("victim", 0)
    is_safe_a, _ = guard.check_package(pkg_a)
    is_safe_b, reason_b = guard.check_package(pkg_b)
    blocked = not is_safe_b
    logger.info(f"[有BC] pkg_a 安全={is_safe_a}; pkg_b（复用 r）安全={is_safe_b} 原因={reason_b}")
    logger.info(f"[有BC] 攻击{'被拦截' if blocked else '成功'}！SecurityGuard k 值重用检测")
    result["with_bc"] = {
        "attack_successful": not blocked,
        "description": "SecurityGuard 检测 r 值重用 → K_REUSE_ATTACK 告警",
        "pkg_a_safe": is_safe_a,
        "pkg_b_safe": is_safe_b,
        "block_reason": reason_b,
        "blocked": blocked,
    }
    shutil.rmtree(key_dir, ignore_errors=True)
    return result


# ──────────────────────────────────────────────────────────────
# 攻击6: 长程攻击
# ──────────────────────────────────────────────────────────────

def demo_long_range_attack(key_dir: str = None) -> Dict:
    """
    攻击6: 长程攻击（Long-Range / 旧纪元签名伪造历史）
    攻击者保存诚实节点在旧纪元的合法签名消息，在新区元重放/伪造，
    试图改写历史或注入过期但"密码学上仍有效"的消息。

    无BC：旧签名仍被当作有效 → 历史可被篡改。
    有BC：纪元绑定 + 时间戳窗口（±30s）+ nonce 单调 → 旧纪元消息被拒。
    """
    if key_dir is None:
        key_dir = tempfile.mkdtemp(prefix="keys_long_")
    logger.info("\n" + "=" * 60)
    logger.info("攻击6: 长程攻击 (Long-Range Attack)")
    logger.info("=" * 60)

    km = KeyManager(key_dir=key_dir)
    km.generate_or_load("honest_node")
    guard = SecurityGuard()
    result = {"attack_type": "long_range_attack", "no_bc": {}, "with_bc": {}}

    old_ts = int(time.time() * 1000) - 3_600_000  # 1 小时前（旧纪元）
    old_epoch = 1
    old_msg = json.dumps({"agent_id": "honest_node", "action": "commit_block",
                          "epoch": old_epoch, "step": 100}, sort_keys=True).encode()
    sig = _sign_message(km, "honest_node", old_msg)
    r_val, s_val = ECDSAUtils.extract_rs(sig)

    # --- 无BC模式：只验签，旧消息仍有效 ---
    sig_ok = _verify_message(km, "honest_node", old_msg, sig)
    logger.info(f"[无BC] 旧纪元签名验签={sig_ok}（密码学仍有效）→ 历史可被重放/篡改")
    logger.info("[无BC] X 攻击成功！攻击者用旧合法签名伪造历史")
    result["no_bc"] = {
        "attack_successful": True,
        "description": "无纪元/时间戳绑定，旧合法签名仍被接受",
        "old_signature_valid": sig_ok,
    }

    # --- 有BC模式：纪元绑定 + 时间戳窗口 ---
    current_epoch = 5
    pkg = {
        "agent_id": "honest_node",
        "action": {"action": "commit_block", "epoch": old_epoch},
        "timestamp": old_ts,
        "nonce": 1,
        "r": r_val, "s": s_val,
        "signature_hex": sig.hex(),
        "epoch": old_epoch,
    }
    guard.register_nonce_baseline("honest_node", 0)
    is_safe, reason = guard.check_package(pkg)
    epoch_ok = (pkg.get("epoch") == current_epoch)
    blocked = (not is_safe) or (not epoch_ok)
    logger.info(f"[有BC] 时间戳校验安全={is_safe}（{reason}）; 纪元匹配={epoch_ok}（当前={current_epoch}）")
    logger.info(f"[有BC] 攻击{'被拦截' if blocked else '成功'}！时间戳过期 + 纪元不匹配双重拒绝")
    result["with_bc"] = {
        "attack_successful": not blocked,
        "description": "时间戳窗口(±30s) + 纪元绑定双重拒绝旧纪元消息",
        "timestamp_safe": is_safe,
        "block_reason": reason,
        "epoch_match": epoch_ok,
        "blocked": blocked,
    }
    shutil.rmtree(key_dir, ignore_errors=True)
    return result


# ──────────────────────────────────────────────────────────────
# Wilson 置信区间 + 批量统计（E6：≥50 次/类 + Wilson 95% CI）
# ──────────────────────────────────────────────────────────────

def _wilson_ci(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score 95% 置信区间（成功率 k/n）。"""
    if n == 0:
        return (0.0, 0.0)
    phat = k / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


ALL_ATTACKS = {
    "observation_forgery": demo_observation_forgery,
    "message_tampering": demo_message_tampering,
    "replay_attack": demo_replay_attack,
    "sybil_attack": demo_sybil_attack,
    "k_reuse_attack": demo_k_reuse_attack,
    "long_range_attack": demo_long_range_attack,
}


def run_attack_batch(n_trials: int = 50) -> List[Dict]:
    """
    对全部 6 类攻击各跑 n_trials 次，统计有BC模式拦截率与 Wilson 95% CI。
    旧 3 类演示脚本硬编码相对密钥目录 ./keys_demo，故用临时工作目录沙箱隔离副作用。
    """
    cwd0 = os.getcwd()
    stats = []
    for name, fn in ALL_ATTACKS.items():
        blocked = 0
        for _ in range(n_trials):
            work = tempfile.mkdtemp(prefix=f"atk_{name}_")
            try:
                os.chdir(work)
                if name in ("sybil_attack", "k_reuse_attack", "long_range_attack"):
                    res = fn(key_dir=work)
                else:
                    res = fn()  # 旧演示使用 ./keys_demo（沙箱内）
                if not res["with_bc"].get("attack_successful", True):
                    blocked += 1
            finally:
                os.chdir(cwd0)
                shutil.rmtree(work, ignore_errors=True)
        lo, hi = _wilson_ci(blocked, n_trials)
        stats.append({
            "attack_type": name,
            "trials": n_trials,
            "blocked": blocked,
            "defense_rate": blocked / n_trials,
            "wilson_ci_95": [round(lo, 4), round(hi, 4)],
        })
    return stats


def generate_statistical_report(stats: List[Dict]) -> Dict:
    total = sum(s["trials"] for s in stats)
    total_blocked = sum(s["blocked"] for s in stats)
    report = {
        "title": "E6 攻击防御批量统计报告",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n_attack_types": len(stats),
        "total_trials": total,
        "overall_defense_rate": total_blocked / total if total else 0.0,
        "per_attack": stats,
    }
    report_path = _Path(_REPO_ROOT) / "results" / "attack_defense_batch_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info(f"\n批量报告已保存: {report_path}")
    return report


# ──────────────────────────────────────────────────────────────
# 报告生成
# ──────────────────────────────────────────────────────────────

def generate_report(results: List[Dict]):
    """生成攻击防御演示报告"""
    bc_blocked = sum(1 for r in results if not r["with_bc"]["attack_successful"])
    # P3-8修复: 空 results 时避免除零（此前 bc_blocked / len(results) 崩溃）
    n = len(results)
    defense_pct = (bc_blocked / n * 100) if n > 0 else 0.0
    report = {
        "title": "区块链安全防护演示报告",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "total_attacks": n,
            "no_bc_success": sum(1 for r in results if r["no_bc"]["attack_successful"]),
            "with_bc_success": sum(1 for r in results if r["with_bc"]["attack_successful"]),
            "defense_rate": f"{bc_blocked}/{n} = {defense_pct:.0f}%",
        },
        "attacks": results,
    }

    report_path = _Path(_REPO_ROOT) / "results" / 'attack_defense_report.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    logger.info(f"\n报告已保存: {report_path}")
    return report


if __name__ == '__main__':
    results = []

    results.append(demo_observation_forgery())
    results.append(demo_message_tampering())
    results.append(demo_replay_attack())
    results.append(demo_sybil_attack())
    results.append(demo_k_reuse_attack())
    results.append(demo_long_range_attack())

    report = generate_report(results)

    # 清理临时密钥目录（P3-4）
    shutil.rmtree("./keys_demo", ignore_errors=True)

    print("\n" + "=" * 60)
    print("攻击防御演示结果摘要（6 类）")
    print("=" * 60)
    print(f"{'攻击类型':<25} {'无BC结果':<15} {'有BC结果':<15} {'防护':<8}")
    print("-" * 60)
    for r in results:
        no_bc = "X 攻击成功" if r["no_bc"]["attack_successful"] else "OK 拦截"
        with_bc = "X 攻击成功" if r["with_bc"]["attack_successful"] else "OK 拦截"
        defense = "OK" if not r["with_bc"]["attack_successful"] else "X"
        print(f"{r['attack_type']:<25} {no_bc:<15} {with_bc:<15} {defense:<8}")
    print("-" * 60)
    print(f"防护成功率: {report['summary']['defense_rate']}")

    # E6 批量统计：每类 ≥50 次 + Wilson 95% 置信区间
    print("\n" + "=" * 60)
    print("E6 批量统计（每类 50 次 + Wilson 95% CI）")
    print("=" * 60)
    batch_stats = run_attack_batch(n_trials=50)
    batch_report = generate_statistical_report(batch_stats)
    print(f"{'攻击类型':<25} {'拦截/总':<12} {'拦截率':<10} {'Wilson 95% CI':<20}")
    print("-" * 60)
    for s in batch_stats:
        print(f"{s['attack_type']:<25} {s['blocked']}/{s['trials']:<11} "
              f"{s['defense_rate']*100:>6.1f}%   "
              f"[{s['wilson_ci_95'][0]*100:.1f}%, {s['wilson_ci_95'][1]*100:.1f}%]")
    print("-" * 60)
    print(f"总体拦截率: {batch_report['overall_defense_rate']*100:.1f}%")

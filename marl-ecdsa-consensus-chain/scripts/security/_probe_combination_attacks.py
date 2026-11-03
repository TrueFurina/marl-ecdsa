# -*- coding: utf-8 -*-
"""组合攻击实测（2026-10-15）

背景：既有六类攻击（scripts/legacy/analysis/attack_defense_demo.py）是**逐类独立**
注入的，从未测试「单类看合法、组合起来绕过」的攻击。本脚本用真实模块
（真 KeyManager / 真 SecurityGuard / 真承诺绑定公式）实测四组组合攻击，
不预设结论——防住即报告防住，绕过即如实报告绕过。

组合清单（威胁模型：恶意节点持有自己合法私钥，可对任意内容自签）：
  C1 开局虚假承诺：承诺 H(fake_position) 上链，后续全程报 fake
     → 承诺绑定只比对「报的 vs 承诺的」，防的是中途改口，防不了开局撒谎
  C2 阈值下持续作恶：每个包时间戳/nonce/r 均合法 ⇒ fail_count 恒 0
     → SecurityGuard 的 fail_count 只统计「检测失败」，不统计「作恶成功」
  C3 r 字段省略：构造包不带 r ⇒ _check_r_reuse 直接 return True
     → 防御纵深缺口（检测被静默跳过）
  C4 FIFO 淘汰后重用：发 >MAX_R_ENTRIES 个包挤掉旧 r，再重用早期 r
     → 检测窗口被上限截断

口径纪律：
  - 承诺绑定公式与 demo_observation_forgery 逐位一致：
    sha256(json.dumps(position, sort_keys=True).encode()).hexdigest()
  - SecurityGuard 直接用生产类，不重写近似
  - 密钥用真 KeyManager 生成（临时目录，用完清理）
"""
import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from blockchain.crypto.key_manager import KeyManager
from blockchain.crypto.security_guard import SecurityGuard

AGENT = "malicious_agent"
TRUE_POS = {"x": 0.8, "y": 0.3, "agent_id": AGENT}
FAKE_POS = {"x": 0.5, "y": 0.5, "agent_id": AGENT}


def _h(pos) -> str:
    """承诺绑定口径：与 demo_observation_forgery 逐位一致"""
    return hashlib.sha256(
        json.dumps(pos, sort_keys=True).encode()
    ).hexdigest()


def _pkg(nonce: int, position, omit_r: bool = False, r: int = None) -> dict:
    """构造一个「合法外观」的签名包：时间戳在窗口内、nonce 递增。"""
    p = {
        "agent_id": AGENT,
        "position": position,
        "timestamp": int(time.time() * 1000),
        "nonce": nonce,
    }
    if not omit_r:
        p["r"] = r if r is not None else 1000 + nonce
    return p


def _banner(title: str):
    print("\n" + "=" * 66)
    print(title)
    print("=" * 66)


def c1_false_commitment():
    """C1：开局承诺假位置，后续全程自洽 → 承诺绑定是否拦截？"""
    _banner("C1 开局虚假承诺（commit-time lying）")
    km_dir = tempfile.mkdtemp(prefix="keys_c1_")
    try:
        km = KeyManager(key_dir=km_dir)
        km.generate_or_load(AGENT)
        # 开局阶段：攻击者承诺的「不是」真实位置，而是伪造位置的哈希
        commit_hash = _h(FAKE_POS)          # ← 关键：承诺的就是假位置
        commit_msg = json.dumps(
            {"agent_id": AGENT, "commit": commit_hash}, sort_keys=True
        )
        priv = km.get_private_key(AGENT)
        from blockchain.crypto.ecdsa_utils import ECDSAUtils
        commit_sig = ECDSAUtils.sign(priv, commit_msg.encode())
        sig_ok = ECDSAUtils.verify(km.get_public_key(AGENT),
                                   commit_msg.encode(), commit_sig)

        # 后续 5 个回合：全程报 fake_position（与假承诺自洽）
        results = []
        for step in range(1, 6):
            reported = FAKE_POS
            # 链上承诺绑定校验（与 demo 同公式）
            commit_match = (_h(reported) == commit_hash)
            blocked = not commit_match
            results.append(blocked)
        all_blocked = all(results)
        print(f"  开局承诺 H(fake_position) 上链，签名有效={sig_ok}")
        print(f"  后续 5 回合全程报 fake_position（与承诺自洽）")
        print(f"  承诺绑定逐回合 blocked: {results}")
        print(f"  → {'✅ 被拦截' if all_blocked else '❌ 攻击成功：全程通过承诺绑定'}")
        return {
            "case": "C1_false_commitment",
            "attack_successful": not all_blocked,
            "commit_signature_valid": sig_ok,
            "rounds_blocked": results,
            "note": "承诺绑定防中途改口，不防开局撒谎；无任何机制校验开局承诺的真伪",
        }
    finally:
        shutil.rmtree(km_dir, ignore_errors=True)


def c2_subliminal_persistent():
    """C2：每个包都合法 ⇒ fail_count 恒 0 ⇒ risk_level 恒 NORMAL"""
    _banner("C2 阈值下持续作恶（包全合法 ⇒ fail_count 不涨）")
    guard = SecurityGuard()
    N = 100
    risk_levels = []
    for i in range(1, N + 1):
        pkg = _pkg(i, FAKE_POS)      # 时间戳窗口内 + nonce 严格递增 + r 全新
        ok, reason = guard.check_package(pkg)
        assert ok, f"合法包不应被拦: {reason}"
        risk_levels.append(guard.get_risk_level(AGENT))
    distinct = set(risk_levels)
    fail_count = guard.get_fail_count(AGENT)
    print(f"  连续 {N} 个『合法外观』包（报的全是伪造位置）")
    print(f"  SecurityGuard.check_package 全部通过；fail_count={fail_count}")
    print(f"  risk_level 全程取值: {distinct}")
    print(f"  → {'✅ 风险升级' if distinct != {'NORMAL'} else '❌ 全程 NORMAL：作恶不计入 fail_count'}")
    return {
        "case": "C2_subliminal_persistent",
        "attack_successful": distinct == {"NORMAL"},
        "packages_sent": N,
        "fail_count": fail_count,
        "risk_levels_seen": sorted(distinct),
        "note": "fail_count 只统计安全检测失败，不统计作恶成功；MAX_FAIL_COUNT 形同虚设",
    }


def c3_omit_r():
    """C3：省略 r 字段 ⇒ k 重用检测被静默跳过"""
    _banner("C3 r 字段省略（k 重用检测静默跳过）")
    guard = SecurityGuard()
    # 同一 r 出现两次：正常路径第二次必被拦
    p1 = _pkg(1, TRUE_POS, r=4242)
    p2 = _pkg(2, TRUE_POS, r=4242)
    ok1, r1 = guard.check_package(p1)
    ok2, r2 = guard.check_package(p2)
    normal_blocked = (ok1 and not ok2)
    # 省略 r：同 r 也不检测
    guard2 = SecurityGuard()
    q1 = _pkg(1, TRUE_POS, omit_r=True, r=4242)
    q2 = _pkg(2, TRUE_POS, omit_r=True, r=4242)
    okq1, _ = guard2.check_package(q1)
    okq2, _ = guard2.check_package(q2)
    print(f"  对照组（带 r）：首次 {ok1} / 同 r 二次 {ok2}（{r2[:40] if not ok2 else ''}）")
    print(f"  省略 r：首次 {okq1} / 同 r 二次 {okq2}")
    print(f"  → {'✅ 一致拦截' if (okq1 and not okq2) else '❌ 省略 r 后检测被跳过（防御纵深缺口）'}")
    return {
        "case": "C3_omit_r",
        "attack_successful": (okq1 and okq2),
        "control_blocked": normal_blocked,
        "note": "security_guard.py:111-112 `if r is None: return True`。"
                "可达性受限于 sign_action 自动 extract_rs 填 r：攻击者须绕过签名服务"
                "直接构造包才能省略 r，且收益仅是让'私钥泄露检测'失效（伤害检测机制"
                "本身而非系统安全），故列为纵深缺口，不计入实时漏洞。",
    }


def c4_fifo_eviction():
    """C4：FIFO 淘汰后重用早期 r"""
    _banner("C4 FIFO 淘汰后重用（检测窗口被 MAX_R_ENTRIES 截断）")
    guard = SecurityGuard()
    MAXN = guard.MAX_R_ENTRIES
    # 先发 MAXN+2 个全新 r 的包，把最早的两个 r 挤出 registry
    for i in range(1, MAXN + 3):
        pkg = _pkg(i, TRUE_POS, r=500000 + i)
        ok, _ = guard.check_package(pkg)
        assert ok, f"前置填充包 {i} 不应被拦"
    # 重用最早被淘汰的 r=500001
    replay = _pkg(MAXN + 100, TRUE_POS, r=500001)
    ok, reason = guard.check_package(replay)
    print(f"  填充 {MAXN + 2} 个包（r 全部唯一）后，重用最早期的 r=500001")
    print(f"  check_package → {ok}（{reason[:40]}）")
    print(f"  → {'✅ 仍被检测' if not ok else '❌ 重用未被检测（已被 FIFO 淘汰）'}")
    return {
        "case": "C4_fifo_eviction",
        "attack_successful": ok,
        "max_r_entries": MAXN,
        "packages_to_evict": MAXN + 2,
        "note": "r_registry 有上限，淘汰后历史 r 不再受检；攻击成本 = MAXN+2 个合法包",
    }


def main():
    results = [
        c1_false_commitment(),
        c2_subliminal_persistent(),
        c3_omit_r(),
        c4_fifo_eviction(),
    ]
    # 威胁可达性分级（防夸大：4/4 绕过 ≠ 4 个同等级漏洞）
    #   real        = 正常路径可达，构成实际伤害
    #   amplifier   = 单独无伤害，放大其他攻击的感知盲区
    #   depth_gap   = 需绕过签名服务构造包，威胁面小，属纵深缺口
    reach = {
        "C1_false_commitment": "real",
        "C2_subliminal_persistent": "amplifier",
        "C3_omit_r": "depth_gap",
        "C4_fifo_eviction": "depth_gap",
    }
    _banner("汇总（含威胁可达性分级）")
    n_success = sum(1 for r in results if r["attack_successful"])
    for r in results:
        mark = "❌ 绕过" if r["attack_successful"] else "✅ 拦截"
        print(f"  {mark}  [{reach[r['case']]:>10s}]  {r['case']}")
    real_hits = [r["case"] for r in results
                 if r["attack_successful"] and reach[r["case"]] == "real"]
    print(f"\n  {n_success}/{len(results)} 组绕过；其中正常路径可达（real）: {real_hits or '无'}")
    print("  real=构成实际伤害 / amplifier=放大其他攻击盲区 / depth_gap=需绕过签名服务的纵深缺口")
    for r in results:
        r["reachability"] = reach[r["case"]]
    out = Path(__file__).resolve().parent / "combination_attack_result.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  结果已写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

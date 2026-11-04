# -*- coding: utf-8 -*-
"""组合攻击行为守卫（2026-10-15）

钉住四组组合攻击的**实测行为事实**（scripts/security/_probe_combination_attacks.py）。
这些测试不守护"已修复"，而守护"已测量的边界"——价值在防两件事：
  1. 将来有人声称"承诺绑定能防撒谎"时，本文件会红（它防不住开局撒谎）
  2. 若将来修复了其中某项，翻转对应断言即有明确信号，不会无声退化

威胁可达性分级（与探针一致）：
  real       = 正常路径可达，构成实际伤害（C1 开局虚假承诺）
  amplifier  = 单独无伤害，放大其他攻击的感知盲区（C2 fail_count 无感知）
  depth_gap  = 需绕过签名服务构造包，纵深缺口（C3 省略 r）

2026-11-03 变更：C4（FIFO 淘汰后重用）已由 security_guard 的淘汰摘要档案关闭，
对应断言已按本节约定翻转；残留边界（档案仅进程内有效）另有一条测试钉住。

诚实边界：C1 不是实现 bug，是承诺机制的设计边界——无外部真值源时，
任何承诺-揭示方案都无法验证开局真伪。修复需引入受信位置登记，属设计变更。
"""
import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from blockchain.crypto.ecdsa_utils import ECDSAUtils
from blockchain.crypto.key_manager import KeyManager
from blockchain.crypto.security_guard import SecurityGuard

AGENT = "malicious_agent"
TRUE_POS = {"x": 0.8, "y": 0.3, "agent_id": AGENT}
FAKE_POS = {"x": 0.5, "y": 0.5, "agent_id": AGENT}


def _h(pos) -> str:
    """承诺绑定口径：与 demo_observation_forgery 逐位一致"""
    return hashlib.sha256(json.dumps(pos, sort_keys=True).encode()).hexdigest()


def _pkg(nonce: int, position, omit_r: bool = False, r: int = None) -> dict:
    p = {
        "agent_id": AGENT,
        "position": position,
        "timestamp": int(time.time() * 1000),
        "nonce": nonce,
    }
    if not omit_r:
        p["r"] = r if r is not None else 1000 + nonce
    return p


# ---------------------------------------------------------------------------
# C1 —— 开局虚假承诺（real）：承诺绑定防中途改口，不防开局撒谎
# ---------------------------------------------------------------------------

def test_c1_false_commitment_passes_binding():
    """开局承诺 H(fake)，后续全程报 fake → 承诺绑定逐回合放行（实测行为）。"""
    key_dir = tempfile.mkdtemp(prefix="test_c1_")
    try:
        km = KeyManager(key_dir=key_dir)
        km.generate_or_load(AGENT)
        commit_hash = _h(FAKE_POS)              # 承诺的就是假位置
        commit_msg = json.dumps({"agent_id": AGENT, "commit": commit_hash},
                                sort_keys=True)
        priv = km.get_private_key(AGENT)
        sig = ECDSAUtils.sign(priv, commit_msg.encode())
        assert ECDSAUtils.verify(km.get_public_key(AGENT),
                                 commit_msg.encode(), sig), "承诺签名应有效"

        # 5 个回合全程自洽 → 无一回合被承诺绑定拦截
        blocked = [(_h(FAKE_POS) != commit_hash) for _ in range(5)]
        assert not any(blocked), "开局假承诺下承诺绑定应全程放行（机制边界）"
    finally:
        shutil.rmtree(key_dir, ignore_errors=True)


def test_c1_control_honest_commit_then_lie_is_blocked():
    """对照组：开局承诺真位置、中途改口报假 → 必须被拦（证明绑定确实在工作）。"""
    commit_hash = _h(TRUE_POS)
    # 中途改口
    assert _h(FAKE_POS) != commit_hash, "诚实承诺后报假位置应不匹配"
    # 若这条红，说明承诺绑定本身坏了，而不是 C1 的边界问题


def test_c1_mismatch_is_detectable_when_committed_honestly():
    """口径锚点：承诺公式与 demo_observation_forgery 一致（防将来改公式静默失效）。"""
    assert _h(TRUE_POS) == hashlib.sha256(
        json.dumps(TRUE_POS, sort_keys=True).encode()).hexdigest()
    assert _h(TRUE_POS) != _h(FAKE_POS)


# ---------------------------------------------------------------------------
# C2 —— 阈值下持续作恶（amplifier）：fail_count 只统计检测失败
# ---------------------------------------------------------------------------

def test_c2_legal_looking_packages_never_raise_risk():
    """连续 100 个合法外观包（内容全假）→ fail_count 恒 0、risk_level 恒 NORMAL。"""
    guard = SecurityGuard()
    for i in range(1, 101):
        ok, reason = guard.check_package(_pkg(i, FAKE_POS))
        assert ok, f"合法外观包不应被拦: {reason}"
    assert guard.get_fail_count(AGENT) == 0
    assert guard.get_risk_level(AGENT) == "NORMAL"


def test_c2_control_rejected_packages_do_raise_risk():
    """对照组：被拦的包必须涨 fail_count（证明 risk_level 确实在工作）。"""
    guard = SecurityGuard()
    bad = _pkg(1, TRUE_POS)
    bad["timestamp"] = 1                      # 远古时间戳 → 必被拦
    ok, _ = guard.check_package(bad)
    assert not ok
    assert guard.get_fail_count(AGENT) >= 1
    assert guard.get_risk_level(AGENT) in ("WARNING", "DANGER")


# ---------------------------------------------------------------------------
# C3 —— r 字段省略（depth_gap）：检测被静默跳过
# ---------------------------------------------------------------------------

def test_c3_omitting_r_skips_k_reuse_detection():
    """省略 r ⇒ 同 r 二次出现也不拦（对照组证明带 r 时能拦）。"""
    # 对照组：带 r，同 r 二次必拦
    g1 = SecurityGuard()
    ok1, _ = g1.check_package(_pkg(1, TRUE_POS, r=4242))
    ok2, _ = g1.check_package(_pkg(2, TRUE_POS, r=4242))
    assert ok1 and not ok2, "对照组失效：带 r 时同 r 二次应被拦"

    # 实测：省略 r，同 r 二次放行
    g2 = SecurityGuard()
    q1, _ = g2.check_package(_pkg(1, TRUE_POS, omit_r=True, r=4242))
    q2, _ = g2.check_package(_pkg(2, TRUE_POS, omit_r=True, r=4242))
    assert q1 and q2, "省略 r 后检测被跳过（纵深缺口，本条钉住现状）"


def test_c3_sign_action_always_fills_r():
    """口径锚点：正常签名路径必填 r ⇒ C3 须绕过签名服务才可达（威胁面小的依据）。"""
    key_dir = tempfile.mkdtemp(prefix="test_c3_")
    try:
        km = KeyManager(key_dir=key_dir)
        km.generate_or_load("agent_x")
        priv = km.get_private_key("agent_x")
        pkg = ECDSAUtils.sign_action("agent_x", priv, "move", nonce=1)
        assert "r" in pkg and pkg["r"] is not None, "sign_action 必须自动填 r"
    finally:
        shutil.rmtree(key_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# C4 —— FIFO 淘汰后重用：检测窗口被 MAX_R_ENTRIES 截断
#
# 2026-11-03 翻转：原断言钉的是「淘汰即可重用」的旧现状（depth_gap）。
# security_guard 引入淘汰摘要档案后，被挤出 _r_registry 的 r 仍能被认出，
# 该缺口关闭 —— 按本文件开头的约定「修复后翻转对应断言」，此处改为钉住新事实。
# ---------------------------------------------------------------------------

def test_c4_evicted_r_is_still_detected():
    """固定填充 1002 个包后，重用最早期的 r **仍被拦下**（2026-11-03 关闭 depth_gap）。

    旧实现只有 `_r_registry` 这一张 FIFO 表：淘汰即遗忘，于是攻击成本仅为
    「先发 MAX_R_ENTRIES 个合法包」就能重放任意早期 r。现实现淘汰时把 r 的
    摘要写入 `_r_evicted_digests`，再次出现照样判为重用来。

    注意：填充量必须写死 1002 而不是 MAX_R_ENTRIES+2 —— 否则上限被调大时
    填充量跟着涨，测试恒绿、钉不住具体上限值（变异验证实测过这个缺陷）。
    """
    guard = SecurityGuard()
    assert guard.MAX_R_ENTRIES == 1000, (
        f"MAX_R_ENTRIES 被改为 {guard.MAX_R_ENTRIES}：r_registry 检测窗口是设计决策，"
        "变更须显式评审（本断言即闸门）"
    )
    for i in range(1, 1003):
        ok, _ = guard.check_package(_pkg(i, TRUE_POS, r=500000 + i))
        assert ok, f"前置填充包 {i} 不应被拦"

    # 500001 / 500002 已被 FIFO 挤出 `_r_registry`（只剩 500003..501002）
    assert 500001 not in guard._r_registry[AGENT], "前置条件失效：500001 未被淘汰"

    ok, reason = guard.check_package(_pkg(1100, TRUE_POS, r=500001))
    assert not ok, "被 FIFO 淘汰的 r 重用必须仍被拦下（不得因淘汰而放行）"
    assert "历史档案" in reason, f"拦截理由应指明命中淘汰档案，实际：{reason}"

    # 淘汰必须留痕：两条被淘汰 + 告警为降级（静默遗忘等于给攻击者留窗口）
    st = guard.get_detection_status()
    assert st["evicted_per_agent"].get(AGENT) == 2, st
    assert st["evicted_digest_count"] == 2, st
    assert st["is_degraded"] is True, st


def test_c4_residual_archive_is_in_memory_only():
    """残留边界：**没有状态文件**的进程，重启即遗忘 —— 不得声称 C4 已彻底修复。

    本测存在的意义是防过度宣称。2026-11-04 补了一条：`_r_evicted_digests` 已随
    `to_snapshot()` 落盘（`SigningService.save_state` 那条路径），所以"重启即遗忘"
    现在**只对裸 `SecurityGuard()` 成立**——即从未调用过 save_state/load_state 的
    进程。仍在的残留是**多副本**：每个副本各持一张表，A 副本淘汰的 r 在 B 副本
    看来仍是新的（除非共享同一份状态文件，而那会引入写冲突，属存储层设计，
    不在检测器内解决）。

    因此本测钉的是"裸进程不共享档案"这一事实；档案跨重启的部分由
    `test_security_guard_persistence.py::test_snapshot_roundtrip_preserves_evicted_archive`
    从正面钉住。两者不矛盾：一个锁"没落盘就没有"，一个锁"落了盘就还在"。
    """
    guard = SecurityGuard()
    for i in range(1, 1003):
        guard.check_package(_pkg(i, TRUE_POS, r=500000 + i))
    assert guard._r_evicted_digests, "前置条件失效：无淘汰记录"

    fresh = SecurityGuard()          # 模拟裸进程重启（未加载任何状态文件）
    ok, _ = fresh.check_package(_pkg(1, TRUE_POS, r=500001))
    assert ok, "裸进程间不应共享档案；若此断言变红，说明档案成了全局单例/隐式落盘，请同步更新本文档"


def test_c4_control_within_window_reuse_is_detected():
    """对照组：未超上限时同 r 二次必拦（证明检测本身有效，只是有窗口上限）。"""
    guard = SecurityGuard()
    ok1, _ = guard.check_package(_pkg(1, TRUE_POS, r=777))
    ok2, _ = guard.check_package(_pkg(2, TRUE_POS, r=777))
    assert ok1 and not ok2, "窗口内 r 重用应被检测"


# ---------------------------------------------------------------------------
# 结构性守卫 —— 探针与测试口径不得漂移
# ---------------------------------------------------------------------------

def test_probe_script_exists():
    """探针脚本必须存在（测试结论的可复现来源）。"""
    probe = Path(__file__).resolve().parents[1] / "scripts" / "security" / \
        "_probe_combination_attacks.py"
    assert probe.exists(), "组合攻击探针脚本缺失"

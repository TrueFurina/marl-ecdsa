"""
SecurityGuard k值重用检测 —— 三处失效路径的回归锁（2026-11-01 审计）

病灶（三条都在同一个函数 `_check_r_reuse` 里，且都能让**真实的 k 重用被放行**）：

1. 缺 r 一律放行
   `if r is None: return True, 'OK'` —— **签名包**只要不带 r 就绕过整个检测。
   现按"包是否声称被签过"分场景：带 signature_hex/s 的包必须有 r（拒绝），
   非签名包允许缺 r（本来就没有 k 可重用，保持既有 test_r_missing_ok 语义）。
   （用户定案 2026-11-01：分场景，而非无差别 fail-closed。）

2. 淘汰后重用被放行（最严重）
   MAX_R_ENTRIES 满后用 FIFO 挤出旧 r，被挤出的 r 再次出现**无法识别**。
   实测序列 0→1→2→3→0（上限 3）时，第二次 r=0 返回 True。
   而 ECDSA 的 k 重用 = 私钥可被直接推导，这是本模块存在的原因。

3. 全局淘汰可被"灌包"利用
   旧 `_trim_r_registry` 是全局配额：`total_entries > MAX_R_ENTRIES` 时
   从**条目最多的 agent** 身上 pop。于是任意 agent 灌满配额，就能把
   目标 agent 的 r 挤掉——攻击者据此可以定向清空受害者的检测窗口。

三条修复后各自有独立断言；另外两组是反向自检（确保断言不是恒真/恒假）。
"""
import time

import pytest

from blockchain.crypto.security_guard import SecurityGuard


def _pkg(agent_id="agent_0", nonce=1, r=0x1000):
    p = {"agent_id": agent_id, "nonce": nonce,
         "timestamp": int(time.time() * 1000)}
    if r is not None:
        p["r"] = r
    return p


# ── 1. 缺 r 的分场景语义 ────────────────────────────────────────────────────
def test_signed_package_missing_r_is_rejected():
    """**签名包**缺 r -> 拒绝。

    签名必然产生 r；带 signature_hex 却没有 r，说明包被截断/篡改，
    或发送方刻意省掉 r 以绕开 k 重用检测。
    """
    g = SecurityGuard()
    ok, reason = g._check_r_reuse({"agent_id": "a", "signature_hex": "deadbeef"})
    assert ok is False, "签名包缺 r 时放行 = 发送方不填 r 即可绕过 k 重用检测"
    assert "r" in reason


def test_signed_package_missing_r_rejected_via_check_package():
    """端到端：走 check_package 入口同样被拦（确认不是只修了私有方法）。"""
    g = SecurityGuard()
    ok, reason = g.check_package({
        "agent_id": "a", "nonce": 1, "signature_hex": "deadbeef",
        "timestamp": int(time.time() * 1000),
    })
    assert ok is False
    assert g.get_fail_count("a") == 1, "被拒的包必须计入失败次数"


def test_unsigned_package_missing_r_is_allowed():
    """**非签名包**缺 r -> 放行（保持既有 test_r_missing_ok 的语义）。

    没有签名就没有 k 可供重用，这类包（基准脚本 / 退化路径 / 仅统计）
    不应被 k 重用检测拦下。
    """
    g = SecurityGuard()
    ok, reason = g._check_r_reuse({"agent_id": "a"})
    assert ok is True, f"非签名包缺 r 被误拦：{reason}"


def test_s_field_alone_also_counts_as_signed():
    """判定不能只看 signature_hex：只有 s 的包同样是签名残留，必须要求 r。"""
    g = SecurityGuard()
    ok, _ = g._check_r_reuse({"agent_id": "a", "s": 12345})
    assert ok is False


# ── 2. 淘汰后重用仍必须被拦（核心） ────────────────────────────────────────
def test_reuse_after_fifo_eviction_is_caught():
    """MAX_R_ENTRIES 满、旧 r 已被挤出内存后，重用同一个 r 仍必须被拦。

    这是本文件最重要的一条：修复前它返回 True（放行真实重用）。
    """
    g = SecurityGuard()
    g.MAX_R_ENTRIES = 3
    for i, r in enumerate([0, 1, 2, 3]):      # 第 4 条把 r=0 挤出
        ok, _ = g._check_r_reuse(_pkg(nonce=i + 1, r=r))
        assert ok is True, f"首次出现的 r={r} 不应被拦"
    assert 0 not in g._r_registry["agent_0"], "前提：r=0 确实已被淘汰"

    ok, reason = g._check_r_reuse(_pkg(nonce=99, r=0))
    assert ok is False, (
        "r=0 已被 FIFO 淘汰后重用却被放行——k 重用检测存在可复用窗口，"
        "而 ECDSA 的 k 重用可直接推导私钥")
    assert "重用" in reason


def test_evicted_digest_archive_is_populated():
    """淘汰必须进摘要档案——没有档案，第 2 条断言无从成立。"""
    g = SecurityGuard()
    g.MAX_R_ENTRIES = 1
    g._check_r_reuse(_pkg(nonce=1, r=7))
    g._check_r_reuse(_pkg(nonce=2, r=8))
    assert g._r_evicted["agent_0"] == 1
    assert len(g._r_evicted_digests) == 1


def test_detection_status_reports_degradation():
    """淘汰过就必须在自查接口里如实报出来（可观测性）。"""
    g = SecurityGuard()
    g.MAX_R_ENTRIES = 1
    assert g.get_detection_status()["is_degraded"] is False
    g._check_r_reuse(_pkg(nonce=1, r=1))
    g._check_r_reuse(_pkg(nonce=2, r=2))
    st = g.get_detection_status()
    assert st["is_degraded"] is True
    assert st["evicted_per_agent"]["agent_0"] == 1
    assert st["evicted_digest_count"] == 1


# ── 3. 跨 agent 隔离：灌包不能挤掉别人的记录 ───────────────────────────────
def test_flooding_other_agent_cannot_evict_victim():
    """一个 agent 灌满大量 r，不得把**另一个** agent 的记录挤掉。

    修复前 `_trim_r_registry` 是全局配额，会从"条目最多的 agent"身上 pop，
    于是 flooder 的包会让 victim 的 r 消失。
    """
    g = SecurityGuard()
    g.MAX_R_ENTRIES = 2
    assert g._check_r_reuse(_pkg(agent_id="victim", nonce=1, r=7))[0]
    for i in range(10):
        g._check_r_reuse(_pkg(agent_id="flooder", nonce=i + 2, r=1000 + i))
    assert 7 in g._r_registry["victim"], "victim 的 r 被 flooder 挤掉了"
    ok, _ = g._check_r_reuse(_pkg(agent_id="victim", nonce=99, r=7))
    assert ok is False, "victim 重用 r=7 未被拦下"


# ── 反向自检：确保上面几条不是恒真/恒假 ────────────────────────────────────
def test_distinct_r_still_passes():
    """不同 r 必须放行——否则上面所有"被拦"的断言都可能是无条件拒绝。"""
    g = SecurityGuard()
    g.MAX_R_ENTRIES = 3
    for i in range(5):
        ok, _ = g._check_r_reuse(_pkg(nonce=i + 1, r=2000 + i))
        assert ok is True, f"全新的 r={2000+i} 被误拦"


def test_trim_registry_single_definition():
    """`_trim_r_registry` 只能有一份定义。

    曾有第二份（P1-11 的全局配额版）与之重名，按 Python 类体规则后定义者
    静默覆盖前者——改了上面那份等于白改，是最难发现的一类失效。
    """
    src = SecurityGuard.__dict__
    assert "_trim_r_registry" in src
    import inspect
    body = inspect.getsource(SecurityGuard)
    assert body.count("def _trim_r_registry") == 1, (
        "类里出现了多份 _trim_r_registry —— 后者会静默覆盖前者")

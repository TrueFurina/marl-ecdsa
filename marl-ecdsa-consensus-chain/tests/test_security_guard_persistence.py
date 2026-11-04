"""
P1-17 修复验证：SecurityGuard / SigningService 统一快照持久化

证明两件事：
1. 跨「重启」（新建实例 + 加载快照）后，k 值重用检测等安全状态仍能保留；
2. 重启后不会出现「自伤式 DoS」——合法的、比快照里更大的新 nonce 仍被正常接受，
   旧的/更小的 nonce 仍被正确判为重放。
"""
import time
import json

from blockchain.crypto.security_guard import SecurityGuard
from marl.integration.signing_service import SigningService


def _pkg(agent_id, nonce, r, ts=None):
    return {
        'agent_id': agent_id,
        'timestamp': ts if ts is not None else int(time.time() * 1000),
        'nonce': nonce,
        'r': r,
    }


def test_security_guard_snapshot_roundtrip_preserves_k_reuse():
    """to_snapshot / from_snapshot 往返后，k 值重用记录仍保留。"""
    g = SecurityGuard()
    now = int(time.time() * 1000)
    assert g.check_package(_pkg('a', 1, 111, now))[0] is True
    # 同一 r 再次使用 → 判定为 k 值重用攻击
    assert g.check_package(_pkg('a', 2, 111, now))[0] is False

    snap = g.to_snapshot()
    blob = json.dumps(snap)

    # 模拟重启：全新实例 + 从快照恢复
    g2 = SecurityGuard()
    g2.from_snapshot(json.loads(blob))
    # 恢复后同一 r 仍应被识别为重用（持久化生效）
    assert g2.check_package(_pkg('a', 3, 111, now))[0] is False
    # 全新 r 应正常通过（无假阳性）
    assert g2.check_package(_pkg('a', 4, 222, now))[0] is True


def test_security_guard_from_snapshot_handles_garbage_gracefully():
    """快照结构异常时不应崩溃，保留内存状态。"""
    g = SecurityGuard()
    g.from_snapshot(None)
    g.from_snapshot({'r_registry': 'not-a-dict'})
    # 仍可正常工作
    assert g.check_package(_pkg('a', 1, 5))[0] is True


def test_signing_service_persistence_keeps_detection_and_avoids_self_dos(tmp_path):
    """统一快照：重启后保留检测、且合法新 nonce 不被误拦（无自伤式 DoS）。"""
    path = str(tmp_path / 'sg_state.json')

    ss = SigningService(security_guard=SecurityGuard(), n_agents=1)
    now = int(time.time() * 1000)
    g = ss.security_guard
    assert g.check_package(_pkg('agent_0', 1, 999, now))[0] is True
    # 同一 r 复用 → 记录为攻击
    assert g.check_package(_pkg('agent_0', 2, 999, now))[0] is False

    ss.save_state(path)

    # 模拟进程重启：用同一 state_path 新建实例（构造函数会自动 load_state）
    ss2 = SigningService(security_guard=SecurityGuard(), n_agents=1, state_path=path)
    g2 = ss2.security_guard

    # 1) 持久化生效：旧 r 仍被识别为重用
    assert g2.check_package(_pkg('agent_0', 3, 999, now))[0] is False
    # 2) 合法的新 r + 更大的新 nonce(4) → 正常通过（没有自伤式 DoS）
    assert g2.check_package(_pkg('agent_0', 4, 888, now))[0] is True
    # 3) 旧 nonce（比快照里的小）仍被正确判为重放
    assert g2.check_package(_pkg('agent_0', 1, 777, now))[0] is False


def test_signing_service_load_state_missing_file_is_fresh(tmp_path):
    """快照文件不存在时，启动为全新状态，不报错。"""
    path = str(tmp_path / 'no_such_file.json')
    ss = SigningService(security_guard=SecurityGuard(), n_agents=1, state_path=path)
    assert ss._nonce_counters['agent_0'] == 0
    assert ss.security_guard.check_package(_pkg('agent_0', 1, 123))[0] is True


# ---------------------------------------------------------------------------
# 2026-11-04：C4 淘汰档案必须跨重启存活
#
# 病灶（实测）：C4 修复让"被 FIFO 淘汰的 r"在**进程存活期内**仍被拦下，但
# to_snapshot 只导出 r_registry，淘汰档案没进快照。于是重启后：
#   digest_count 由 2 掉到 0；同一个被淘汰的 r 由「历史档案命中」变成「OK」放行；
#   is_degraded 由 True 变回 False —— 系统同时**丢了检测**并**自称未降级**。
# 本组用例把"档案随快照走"钉死。
# ---------------------------------------------------------------------------

def _flood_to_evict(g, agent_id='node_0', seed_rs=(500001, 500002)):
    """先把要淘汰的 r 塞进窗口，再灌满 MAX_R_ENTRIES 条把它挤出去。

    返回 (timestamp, 已用到的最大 nonce)。nonce 必须严格递增，否则会在
    nonce 门就被拦，测不到 r 档案这一层。
    """
    ts = int(time.time() * 1000)
    nonce = 1
    for r in seed_rs:
        ok, why = g.check_package(_pkg(agent_id, nonce, r, ts))
        assert ok, f"置入种子 r 失败：{why}"
        nonce += 1
    for i in range(g.MAX_R_ENTRIES):
        ok, why = g.check_package(_pkg(agent_id, nonce, 600000 + i, ts))
        assert ok, f"灌窗口时被误拦（第 {i} 条）：{why}"
        nonce += 1
    return ts, nonce


def test_snapshot_roundtrip_preserves_evicted_archive():
    """淘汰档案随快照跨重启存活：重启后同一 r 仍被拦、且仍报降级。"""
    g = SecurityGuard()
    ts, nonce = _flood_to_evict(g)

    st = g.get_detection_status()
    assert st['evicted_per_agent'].get('node_0') == 2, f"前置条件失效：{st}"
    assert st['evicted_digest_count'] == 2
    assert st['is_degraded'] is True

    snap = g.to_snapshot()
    blob = json.dumps(snap)

    # 重启前：被淘汰的 r 重用必须被拦（C4 已在内存窗口外生效）
    ok_live, why_live = g.check_package(_pkg('node_0', nonce + 1, 500001, ts))
    assert ok_live is False, "前置条件失效：淘汰后重用在内存里都没被拦"
    assert '历史档案' in why_live

    g2 = SecurityGuard()
    g2.from_snapshot(json.loads(blob))

    st2 = g2.get_detection_status()
    assert st2['evicted_digest_count'] == st['evicted_digest_count'], (
        f"淘汰档案没跨重启存活：重启前 {st['evicted_digest_count']} 条，"
        f"重启后只剩 {st2['evicted_digest_count']} 条")
    assert st2['is_degraded'] is True, "重启后自称未降级 —— 把已滚过窗口这件事瞒掉了"

    ok2, why2 = g2.check_package(_pkg('node_0', nonce + 2, 500001, ts))
    assert ok2 is False, "跨重启后被淘汰的 r 重用被放行 —— C4 缺口在重启处回来了"
    assert '历史档案' in why2


def test_old_snapshot_without_archive_is_backward_compatible():
    """旧版快照（没有淘汰档案字段）必须能加载，退化为空档案而不是报错。"""
    fresh = SecurityGuard().to_snapshot()
    legacy = {k: v for k, v in fresh.items() if k not in ('r_evicted', 'r_evicted_digests')}
    assert 'r_evicted' not in legacy and 'r_evicted_digests' not in legacy

    g = SecurityGuard()
    g.from_snapshot(legacy)          # 不应抛错
    st = g.get_detection_status()
    assert st['evicted_digest_count'] == 0
    assert st['is_degraded'] is False
    # 加载旧快照后检测照常工作（非空转）
    assert g.check_package(_pkg('a', 1, 7))[0] is True


def test_old_snapshot_does_not_wipe_live_archive():
    """旧格式快照加载到"已有档案"的实例上时，不得把档案冲成空。

    缺字段的正确解读是"写快照的那版没有档案功能"，而不是"当时没淘汰过 r"。
    """
    g = SecurityGuard()
    ts, nonce = _flood_to_evict(g, agent_id='node_0')
    assert g.get_detection_status()['evicted_digest_count'] == 2

    legacy = {k: v for k, v in g.to_snapshot().items()
              if k not in ('r_evicted', 'r_evicted_digests')}
    g.from_snapshot(legacy)          # 同一实例加载旧格式快照

    assert g.get_detection_status()['evicted_digest_count'] == 2, "旧快照把内存档案冲掉了"
    ok, why = g.check_package(_pkg('node_0', nonce + 1, 500001, ts))
    assert ok is False, "旧快照加载后，被淘汰的 r 重用被放行"
    assert '历史档案' in why


def test_archive_survives_signing_service_state_file(tmp_path):
    """走真实状态文件（SigningService.save_state → 新实例自动 load_state）。"""
    path = str(tmp_path / 'sg_state_c4.json')

    ss = SigningService(security_guard=SecurityGuard(), n_agents=1, state_path=path)
    g = ss.security_guard
    ts, nonce = _flood_to_evict(g, agent_id='agent_0')
    assert g.get_detection_status()['evicted_digest_count'] == 2
    ss.save_state(path)

    ss2 = SigningService(security_guard=SecurityGuard(), n_agents=1, state_path=path)
    g2 = ss2.security_guard
    ok, why = g2.check_package(_pkg('agent_0', nonce + 1, 500001, ts))
    assert ok is False, "从状态文件重启后，被淘汰的 r 重用被放行"
    assert '历史档案' in why
    assert g2.get_detection_status()['is_degraded'] is True


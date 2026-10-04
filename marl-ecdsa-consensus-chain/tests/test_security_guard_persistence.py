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

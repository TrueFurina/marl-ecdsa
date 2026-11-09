"""
security_guard 淘汰-r 复用检测优化 自验收测试（2026-11-10 自进化）

背景：原 _check_r_reuse 在复用检测的热路径上，对每一个"不在当前 _r_registry 的 r"
都调用 sha256 的 _r_digest 去查 _r_evicted_digests 全局摘要档案。

优化：新增按 agent 的内存集合 _r_evicted_by_agent（O(1) 集合成员判断），
稳态优先走该集合，免去每查一次 sha256；跨重启冷启动场景下该集合为空，
回落到摘要档案查询（_r_evicted_digests 才是真值源）。失败安全：
最坏退化为原行为，绝不漏检 k 重用。

本测试聚焦：
  1. 稳态命中时确实不再调用 _r_digest（优化生效，可被静态验证）。
  2. 被淘汰 r 的复用仍被正确拦下（正确性不退化）。
  3. 跨重启（快照往返）后仍能通过摘要档案拦下（冷启动回落正确）。
  4. reset_agent 清理每 agent 集合，但摘要档案保留 → 复用仍拦（语义一致）。
  5. 对"有淘汰历史 agent"的崭新 r 不误报（不过度触发）。
"""
import pytest

from blockchain.crypto.security_guard import SecurityGuard


def _signed(agent_id, r):
    """构造一个被当作"签名包"的最小 payload，仅供 _check_r_reuse 直接使用。"""
    return {"agent_id": agent_id, "r": r, "signature_hex": "deadbeef"}


def _insert(g, agent_id, r):
    """直接走 r 重用检测入口登记一个 r（绕过 timestamp/nonce，隔离待测逻辑）。"""
    ok, _ = g._check_r_reuse(_signed(agent_id, r))
    assert ok is True, f"fresh r={r} for {agent_id} should be accepted"
    return ok


def _evict_one(g, agent_id, evicted, newer):
    """把 MAX_R_ENTRIES 调到 1，先插入 evicted（最旧）再插入 newer → evicted 被 FIFO 挤出。"""
    g.MAX_R_ENTRIES = 1
    _insert(g, agent_id, evicted)  # 最旧
    _insert(g, agent_id, newer)    # 触发淘汰，evicted 进入 per-agent 集合 + 摘要档案


def test_evicted_reuse_still_caught_with_per_agent_set():
    """被淘汰 r 的复用必须仍被拦下（优化不得破坏正确性）。"""
    g = SecurityGuard()
    _evict_one(g, "a", evicted=1, newer=2)
    ok, reason = g._check_r_reuse(_signed("a", 1))
    assert ok is False
    assert "k值重用" in reason


def test_evicted_lookup_avoids_digest_on_hot_path():
    """稳态命中 per-agent 集合时，不应再调用 _r_digest（优化确实生效）。

    这是对"优化带来收益"的静态、可复现验证：给 _r_digest 包一层计数器，
    在已发生淘汰后做一次复用语义查询，断言计数器为 0（说明走的是 O(1) 集合判断）。
    """
    g = SecurityGuard()
    _evict_one(g, "a", evicted=1, newer=2)

    counter = {"n": 0}
    orig = SecurityGuard._r_digest  # 访问类属性拿到底层函数

    def counting(agent_id, r):
        counter["n"] += 1
        return orig(agent_id, r)

    SecurityGuard._r_digest = staticmethod(counting)
    try:
        ok, _ = g._check_r_reuse(_signed("a", 1))
    finally:
        SecurityGuard._r_digest = staticmethod(orig)

    assert ok is False, "复用必须被拦"
    assert counter["n"] == 0, (
        f"优化未生效：复用查询仍调用了 {counter['n']} 次 _r_digest，"
        "应走 per-agent 内存集合而非每查 sha256"
    )


def test_evicted_lookup_via_digest_after_snapshot():
    """跨重启（快照往返）后 per-agent 集合为空，须靠摘要档案仍能拦下复用。

    验证冷启动回落路径正确，且优化对跨重启正确性零影响。
    """
    g = SecurityGuard()
    _evict_one(g, "a", evicted=1, newer=2)

    snap = g.to_snapshot()
    g2 = SecurityGuard()
    g2.MAX_R_ENTRIES = 1
    g2.from_snapshot(snap)

    # 重启后 per-agent 集合应为空（无法从单向摘要反推 r）
    assert "a" not in g2._r_evicted_by_agent  # 重启后 per-agent 集合应为空（无法从摘要反推 r）

    ok, reason = g2._check_r_reuse(_signed("a", 1))
    assert ok is False, "跨重启后摘要档案必须仍能认出被淘汰的 r"
    assert "k值重用" in reason


def test_reset_agent_clears_per_agent_set_but_keeps_digest():
    """reset_agent 清空每 agent 集合，但保留摘要档案 → 复用仍拦（语义不丢）。"""
    g = SecurityGuard()
    _evict_one(g, "a", evicted=1, newer=2)
    assert 1 in g._r_evicted_by_agent["a"]

    g.reset_agent("a")
    assert "a" not in g._r_evicted_by_agent, "reset 应清理每 agent 淘汰集合"

    # 摘要档案故意保留（见 reset_agent 文档）：复用经 digest 回落仍被拦
    ok, _ = g._check_r_reuse(_signed("a", 1))
    assert ok is False


def test_fresh_r_not_falsely_flagged_for_agent_with_evictions():
    """对"已有淘汰历史 agent"的崭新 r 不得误报（不过度触发）。"""
    g = SecurityGuard()
    _evict_one(g, "a", evicted=1, newer=2)  # per-agent 集合 = {1}
    ok, _ = g._check_r_reuse(_signed("a", 99))
    assert ok is True, "崭新 r=99 不应被已淘汰集合误伤"

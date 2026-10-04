"""
SecurityGuard 更多边界测试（RalphLoop 原子任务 CJ）
覆盖：nonce 基线、重置、告警过滤、综合拦截、统计结构
通过标准：新增 ≥6 项测试全过
"""
import logging
import time

import pytest

from blockchain.crypto.security_guard import SecurityGuard

logging.basicConfig(level=logging.CRITICAL)


@pytest.fixture
def guard():
    return SecurityGuard()


def _pkg(agent_id="agent_0", ts=None, nonce=1, r=0x1000):
    return {
        "agent_id": agent_id,
        "timestamp": ts if ts is not None else int(time.time() * 1000),
        "nonce": nonce,
        "r": r,
    }


class TestNonceBaseline:
    def test_baseline_blocks_lower_nonce(self, guard):
        """基线 nonce=5：nonce<=5 被拦截"""
        guard.register_nonce_baseline("agent_0", 5)
        ok, reason = guard.check_package(_pkg(nonce=5, r=0x2000))
        assert ok is False
        assert "NONCE" in reason.upper() or "REPLAY" in reason.upper()

    def test_baseline_allows_higher_nonce(self, guard):
        """基线 nonce=5：nonce=6 通过"""
        guard.register_nonce_baseline("agent_0", 5)
        ok, _ = guard.check_package(_pkg(nonce=6, r=0x2000))
        assert ok is True


class TestReset:
    def test_reset_all_nonces_default_all(self, guard):
        """reset_all_nonces 无参数 → 重置所有（默认）"""
        guard.check_package(_pkg(nonce=1))
        guard.reset_all_nonces()
        # 重置后 nonce=1 用新 r 可再次通过
        ok, _ = guard.check_package(_pkg(nonce=1, r=0x3000))
        assert ok is True

    def test_reset_agent_clears_fail_counts(self, guard):
        """reset_agent 清空失败计数与风险等级（alerts 历史日志保留，符合实现契约）"""
        for i in range(3):
            guard.check_package(_pkg(nonce=i, ts=int(time.time() * 1000) - 60000))
        assert guard.get_fail_count("agent_0") == 3
        guard.reset_agent("agent_0")
        assert guard.get_fail_count("agent_0") == 0
        assert guard.get_risk_level("agent_0") == "NORMAL"  # 风险等级恢复


class TestAlerts:
    def test_alerts_filter_by_agent(self, guard):
        """get_alerts 按 agent 过滤"""
        guard.check_package(_pkg(agent_id="agent_0", ts=int(time.time() * 1000) - 60000))
        guard.check_package(_pkg(agent_id="agent_1", ts=int(time.time() * 1000) - 60000))
        a0_alerts = guard.get_alerts("agent_0")
        assert len(a0_alerts) == 1
        assert a0_alerts[0]["agent_id"] == "agent_0"

    def test_alerts_all_returns_all(self, guard):
        guard.check_package(_pkg(ts=int(time.time() * 1000) - 60000))
        assert len(guard.get_alerts()) == 1


class TestCombinedChecks:
    def test_timestamp_replay_combined(self, guard):
        """过期时间戳 + 重复 nonce → 拦截（reason 为中文文案）"""
        ts = int(time.time() * 1000) - 60000  # 过期
        ok, reason = guard.check_package(_pkg(ts=ts, nonce=1))
        assert ok is False
        assert "时间戳" in reason or "过期" in reason

    def test_r_reuse_detected(self, guard):
        """相同 r 值重用 → 拦截（k 重用检测，reason 为中文文案）"""
        guard.check_package(_pkg(nonce=1, r=0x1111))
        ok, reason = guard.check_package(_pkg(nonce=2, r=0x1111))  # 同 r 不同 nonce
        assert ok is False
        assert "重用" in reason or "k值" in reason.lower()


class TestStats:
    def test_get_stats_structure(self, guard):
        """get_stats 含告警/失败/风险统计"""
        guard.check_package(_pkg(ts=int(time.time() * 1000) - 60000))
        stats = guard.get_stats()
        assert 'total_alerts' in stats
        assert stats['total_alerts'] >= 1

    def test_get_stats_initial(self, guard):
        """初始统计为零"""
        stats = guard.get_stats()
        assert stats['total_alerts'] == 0
